"""UN Comtrade 全球贸易流采集器
覆盖: 建材品类HS编码维度的全球进出口数据
API: https://comtradeapi.un.org/data/v1/get/ (新V2 API)
需要: 注册获取免费subscription key (comtradedeveloper.un.org)
免费tier: 每次最多250,000条记录, 月度数据延迟2-3个月
"""
import json, os, time
from datetime import datetime, timedelta
from ..utils import fetch_json, cache_get, cache_set, save_raw, log, safe_float, pct_change

COMTRADE_KEY = os.environ.get("UN_COMTRADE_KEY", "")
COMTRADE_BASE = "https://comtradeapi.un.org/data/v1/get"

# 从taxonomy.json中提取的HS编码分组 (按二级品类)
# 仅选取代表性HS编码 (每个品类前3-5个, 减少请求量)
HS_CODE_GROUPS = {
    "瓷砖及配件": ["690721", "690722", "690723", "690410"],
    "地板及配件": ["391810", "441875", "441874", "391890"],
    "建筑板材": ["441231", "441233", "441239", "441012"],
    "石材": ["680293", "680221", "251511", "251512"],
    "浴室和厨房产品": ["691010", "691090", "732410", "732490"],
    "门、窗及其配件": ["441810", "441820", "761010", "830241"],
    "活动房屋与钢结构": ["940610", "940620", "940690"],
    "木材": ["440711", "440719", "440391", "441210"],
    "建筑工业玻璃": ["700800", "700729", "701690"],
    "砖石材料": ["252321", "252329", "252390", "681011"],
    "防水材料": ["680710"],
    "隔热材料": ["392111"],
    "防火材料": ["381600", "680690"],
}

# 主要贸易国 (reporter) 和伙伴国 (partner)
MAJOR_EXPORTERS = ["CN", "DE", "IT", "TR", "IN", "ES", "VN", "TH", "BR", "MX"]
MAJOR_IMPORTERS = ["US", "DE", "GB", "FR", "JP", "AU", "SA", "AE", "CA", "BR"]


def _comtrade_fetch(hs_code: str, period: str = "2024",
                    flow_code: str = "X",
                    reporter: str = "WLD") -> list[dict]:
    """UN Comtrade API请求

    Args:
        hs_code: HS编码 (4-6位)
        period: 年份 "2024" 或月份 "2024-01"
        flow_code: "X"=出口, "M"=进口
        reporter: 报告国代码, "WLD"=全球汇总
    """
    if not COMTRADE_KEY:
        return []

    params = {
        "typeCode": "goods",
        "freqCode": "A",       # 年度
        "clCode": "HS",        # HS分类
        "period": period,
        "reporterCode": reporter,
        "cmdCode": hs_code,
        "flowCode": flow_code,
        "includeDesc": "true",
        "subscription-key": COMTRADE_KEY
    }

    data = fetch_json(COMTRADE_BASE, params=params, timeout=30, retries=1)
    if not data or "data" not in data:
        return []

    results = []
    for item in data["data"]:
        results.append({
            "reporter": item.get("reporterCode", ""),
            "reporter_name": item.get("reporterDesc", ""),
            "partner": item.get("partnerCode", ""),
            "partner_name": item.get("partnerDesc", ""),
            "flow": flow_code,
            "value_usd": safe_float(item.get("primaryValue")),
            "qty_kg": safe_float(item.get("netWgt")),
            "hs_code": hs_code,
            "description": item.get("cmdDesc", ""),
            "period": period
        })
    return results


def collect_category_trade(category: str, hs_codes: list[str],
                            year: str = "2024") -> dict:
    """采集单个品类的全球贸易数据

    Returns:
        {
            "category": "瓷砖及配件",
            "hs_codes": ["690721", ...],
            "total_exports_usd": 12345678,
            "total_imports_usd": 12345678,
            "top_exporters": [{"country": "CN", "value": 5000000}, ...],
            "top_importers": [{"country": "US", "value": 3000000}, ...],
            "unit_price_trend": 2.35,
            "status": "ok"
        }
    """
    log.info(f"  Comtrade: {category} ({len(hs_codes)} HS codes)")

    total_exports = 0
    total_imports = 0
    exporter_totals = {}
    importer_totals = {}

    for hs in hs_codes:
        # 出口数据 (全球报告)
        exports = _comtrade_fetch(hs, period=year, flow_code="X", reporter="WLD")
        for item in exports:
            val = item.get("value_usd") or 0
            total_exports += val
            reporter = item.get("reporter", "")
            if reporter and reporter != "WLD":
                exporter_totals[reporter] = exporter_totals.get(reporter, 0) + val

        # 进口数据
        imports = _comtrade_fetch(hs, period=year, flow_code="M", reporter="WLD")
        for item in imports:
            val = item.get("value_usd") or 0
            total_imports += val
            reporter = item.get("reporter", "")
            if reporter and reporter != "WLD":
                importer_totals[reporter] = importer_totals.get(reporter, 0) + val

        time.sleep(0.3)  # Comtrade限流

    # 排序: top exporters/importers
    top_exporters = sorted(exporter_totals.items(), key=lambda x: -x[1])[:10]
    top_importers = sorted(importer_totals.items(), key=lambda x: -x[1])[:10]

    return {
        "category": category,
        "hs_codes": hs_codes,
        "year": year,
        "total_exports_usd": total_exports,
        "total_imports_usd": total_imports,
        "top_exporters": [{"country": c, "value": v} for c, v in top_exporters],
        "top_importers": [{"country": c, "value": v} for c, v in top_importers],
        "status": "ok"
    }


def collect_all_trade_flows(year: str = None) -> dict:
    """采集所有品类的全球贸易流数据

    Args:
        year: 年份, 默认去年(年度数据延迟2-3个月)
    """
    log.info("=== Collecting UN Comtrade trade flows ===")

    if not COMTRADE_KEY:
        log.warning("UN_COMTRADE_KEY not set, skipping trade flows")
        return {"categories": {}, "status": "no_key", "collected_at": datetime.now().isoformat()}

    if year is None:
        # 年度数据延迟, 取前一年
        year = str(datetime.now().year - 1)

    cache_key = f"comtrade_{year}"
    cached = cache_get(cache_key, "trade_flow", ttl=3600 * 24 * 30)  # 月度缓存
    if cached:
        return cached

    categories = {}
    for category, codes in HS_CODE_GROUPS.items():
        result = collect_category_trade(category, codes, year=year)
        categories[category] = result
        save_raw("trade_flow", f"{category}_{year}", result)
        time.sleep(1)  # 品类间间隔

    output = {
        "categories": categories,
        "year": year,
        "categories_collected": len(categories),
        "collected_at": datetime.now().isoformat(),
        "status": "ok"
    }

    cache_set(cache_key, "trade_flow", output)
    save_raw("trade_flow", f"all_{year}", output)
    log.info(f"Comtrade: {len(categories)} categories for {year}")
    return output


def format_trade_summary(trade_data: dict) -> list[dict]:
    """将贸易数据转化为期刊supplyChain板块格式"""
    if trade_data.get("status") == "no_key":
        return []

    tables = []
    year = trade_data.get("year", "")

    # 总览表: 各品类贸易规模
    overview_data = []
    for cat, data in trade_data.get("categories", {}).items():
        if data.get("total_exports_usd"):
            overview_data.append({
                "item": cat,
                "value": f"${data['total_exports_usd'] / 1e6:.0f}M",
                "change": 0  # YoY需要对比去年数据, P2实现
            })

    if overview_data:
        tables.append({
            "title": f"建材品类全球出口额 ({year})",
            "data": sorted(overview_data, key=lambda x: float(x["value"].replace("$", "").replace("M", "")),
                           reverse=True)
        })

    # 各品类top出口国
    for cat, data in trade_data.get("categories", {}).items():
        exporters = data.get("top_exporters", [])
        if exporters:
            tables.append({
                "title": f"{cat} - Top出口国 ({year})",
                "data": [{"item": e["country"], "value": f"${e['value']/1e6:.1f}M", "change": 0}
                         for e in exporters[:5]]
            })

    return tables


if __name__ == "__main__":
    data = collect_all_trade_flows()
    tables = format_trade_summary(data)
    print(f"\nTrade tables: {len(tables)}")
    for t in tables[:3]:
        print(f"\n{t['title']}:")
        for row in t["data"][:5]:
            print(f"  {row['item']}: {row['value']}")

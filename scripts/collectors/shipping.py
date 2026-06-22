"""海运运价采集器 (v2 - 实测优化)
覆盖: SCFI(上海出口集装箱运价指数) + BDI(波罗的海干散货指数)
数据源:
  - SCFI: sse.net.cn AJAX JSON API (每周五更新, 实测验证可用)
  - BDI: TradingEconomics HTML内嵌JS数据 (BDIY:IND)
"""
import json, re
from datetime import datetime
from ..utils import fetch_json, cache_get, cache_set, save_raw, log, safe_float, pct_change


# ===================== SCFI (JSON API) =====================

SCFI_API = "https://en.sse.net.cn/currentIndex"


def collect_scfi() -> dict:
    """SCFI - 上海出口集装箱运价指数 (JSON API)
    
    返回格式:
    {
        "composite": {"route": "综合指数", "value": 2985.22, "previous": 2726.48, "change_pct": 9.49},
        "routes": [{"route": "欧洲20ft", "value": ..., ...}],
        "date": "2026-06-12",
        "status": "ok"
    }
    """
    log.info("=== Collecting SCFI (SSE JSON API) ===")

    cache_key = "scfi_latest"
    cached = cache_get(cache_key, "shipping", ttl=3600 * 24 * 3)
    if cached:
        return cached

    import requests
    try:
        resp = requests.get(SCFI_API,
                            params={"indexName": "scfi"},
                            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                                     "Accept": "application/json",
                                     "Referer": "https://en.sse.net.cn/indices/scfinew.jsp"},
                            timeout=20)
        if resp.status_code != 200:
            log.warning(f"SCFI fetch failed: HTTP {resp.status_code}")
            return {"composite": None, "routes": [], "date": "", "status": "fetch_failed"}

        data = resp.json().get("data", {})
        current_date = data.get("currentDate", "")
        last_date = data.get("lastDate", "")
        items = data.get("lineDataList", [])

        composite = None
        routes = []

        for item in items:
            props = item.get("properties", {})
            name_en = props.get("lineName_EN", "")
            name_zh = props.get("lineName_ZH", "")
            unit = props.get("unit_EN", "")
            current = safe_float(item.get("currentContent"))
            previous = safe_float(item.get("lastContent"))
            absolute = safe_float(item.get("absolute"))
            percentage = safe_float(item.get("percentage"))
            item_type = item.get("dataItemTypeName", "")

            entry = {
                "route": name_en or name_zh,
                "route_zh": name_zh,
                "value": current,
                "previous": previous,
                "change": absolute,
                "change_pct": percentage,
                "unit": unit
            }

            if item_type == "SCFI_T":
                composite = entry
            else:
                # 只保留有数据的航线
                if current is not None:
                    routes.append(entry)

        result = {
            "composite": composite,
            "routes": routes,
            "date": current_date,
            "last_date": last_date,
            "total_routes": len(items) - 1,  # 去掉综合
            "status": "ok" if composite else "parse_failed"
        }

    except Exception as e:
        log.error(f"SCFI error: {e}")
        result = {"composite": None, "routes": [], "date": "", "status": "fetch_failed"}

    cache_set(cache_key, "shipping", result)
    save_raw("shipping", "scfi", result)

    comp_str = f"{result['composite']['value']:.2f}" if result.get("composite") and result["composite"].get("value") else "N/A"
    chg_str = f"{result['composite']['change_pct']:.2f}%" if result.get("composite") and result["composite"].get("change_pct") else ""
    log.info(f"SCFI composite: {comp_str} ({chg_str}), routes with data: {len(result.get('routes', []))}")
    return result


# ===================== BDI (TradingEconomics) =====================

BDI_TE_URL = "https://tradingeconomics.com/commodity/baltic"


def _parse_te_charts_meta(html: str) -> dict:
    """从TradingEconomics HTML中提取TEChartsMeta数据"""
    match = re.search(r'TEChartsMeta\s*=\s*(\[.*?\]);', html, re.DOTALL)
    if not match:
        return {}

    raw = match.group(1)
    # 清理.NET Date格式
    raw = re.sub(r'"\\/Date\((\d+)\)\\/"', r'\1', raw)

    try:
        data = json.loads(raw)
        if data:
            item = data[0]
            return {
                "value": safe_float(item.get("value")),
                "last": safe_float(item.get("last")),
                "symbol": item.get("symbol", ""),
                "name": item.get("name", ""),
                "full_name": item.get("full_name", ""),
            }
    except json.JSONDecodeError:
        pass
    return {}


def _parse_te_last_update(html: str) -> str:
    """提取TELastUpdate时间戳"""
    matches = re.findall(r"TELastUpdate\s*=\s*'(\d+)'", html)
    if matches:
        ts_str = matches[-1]  # 取最后一个(最新的)
        try:
            dt = datetime.strptime(ts_str[:8], "%Y%m%d")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def collect_bdi() -> dict:
    """BDI - 波罗的海干散货指数 (TradingEconomics HTML解析)

    策略: 抓取tradingeconomics.com/commodity/baltic页面,
          从内嵌JS变量TEChartsMeta提取实时数据
    """
    log.info("=== Collecting BDI (TradingEconomics) ===")

    cache_key = "bdi_latest"
    cached = cache_get(cache_key, "shipping", ttl=3600 * 12)
    if cached:
        return cached

    import requests
    result = {"value": None, "previous": None, "change": None,
              "change_pct": None, "date": "", "source": "tradingeconomics", "status": "unknown"}

    try:
        resp = requests.get(BDI_TE_URL,
                            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                                     "Accept-Language": "en-US,en;q=0.9"},
                            timeout=20)
        if resp.status_code != 200:
            log.warning(f"BDI TE fetch failed: HTTP {resp.status_code}")
            result["status"] = "fetch_failed"
        else:
            meta = _parse_te_charts_meta(resp.text)
            date_str = _parse_te_last_update(resp.text)

            if meta.get("value"):
                value = meta["value"]
                # TE的last字段通常等于value(当前价), 
                # 需要存储历史数据来计算环比
                result["value"] = round(value, 0)
                result["date"] = date_str
                result["symbol"] = meta.get("symbol", "BDIY:IND")
                result["name"] = meta.get("full_name") or meta.get("name", "Baltic Dry Index")
                result["status"] = "ok"

                # 尝试从缓存的前次数据计算环比
                prev_cached = cache_get("bdi_previous", "shipping")
                if prev_cached and prev_cached.get("value"):
                    prev_val = prev_cached["value"]
                    result["previous"] = prev_val
                    result["change"] = round(value - prev_val, 0)
                    result["change_pct"] = pct_change(value, prev_val)

                # 保存当前值供下次环比
                cache_set("bdi_previous", "shipping", {"value": value, "date": date_str})

            else:
                result["status"] = "parse_failed"

    except Exception as e:
        log.error(f"BDI error: {e}")
        result["status"] = "fetch_failed"

    # 备用源: 如TE失败,尝试从 Markets Insider 获取BDI
    if result["status"] != "ok":
        log.info("BDI: TradingEconomics failed, trying fallback source...")
        try:
            fb_url = "https://markets.businessinsider.com/index/baltic-dry-index"
            fb_resp = requests.get(fb_url,
                                   headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                                   timeout=15)
            if fb_resp.status_code == 200:
                # 尝试从HTML提取价格 (多种regex模式)
                price_match = re.search(r'"price":\s*([\d,.]+)', fb_resp.text)
                if not price_match:
                    price_match = re.search(r'class="[^"]*price[^"]*"[^>]*>([\d,.]+)', fb_resp.text)
                if price_match:
                    bdi_val = safe_float(price_match.group(1).replace(",", ""))
                    if bdi_val and bdi_val > 100:  # 合理性检查
                        result["value"] = round(bdi_val, 0)
                        result["source"] = "markets.businessinsider.com"
                        result["status"] = "ok"
                        log.info(f"BDI fallback: {bdi_val}")
        except Exception as e:
            log.warning(f"BDI fallback error: {e}")

    cache_set(cache_key, "shipping", result)
    save_raw("shipping", "bdi", result)

    val_str = f"{result['value']:.0f}" if result.get("value") else "N/A"
    chg_str = f"{result['change_pct']:.1f}%" if result.get("change_pct") else ""
    log.info(f"BDI: {val_str} ({chg_str}) date={result.get('date','')} status={result.get('status')}")
    return result


# ===================== 汇总 & 格式化 =====================

def collect_all_shipping() -> dict:
    """汇总所有海运运价数据"""
    scfi = collect_scfi()
    bdi = collect_bdi()

    # 构建供应面板块数据表
    table_data = []

    if bdi.get("value"):
        table_data.append({
            "item": "BDI(波罗的海干散货)",
            "value": f"{bdi['value']:.0f}",
            "change": bdi.get("change_pct") or 0
        })

    if scfi.get("composite") and scfi["composite"].get("value"):
        c = scfi["composite"]
        table_data.append({
            "item": "SCFI(上海集装箱综合)",
            "value": f"{c['value']:.0f}",
            "change": c.get("change_pct") or 0
        })
        for route in scfi.get("routes", [])[:8]:
            if route.get("value") is not None:
                label = route.get("route", "")
                table_data.append({
                    "item": f"SCFI-{label}",
                    "value": f"{route['value']:.0f}",
                    "change": route.get("change_pct") or 0
                })

    return {
        "scfi": scfi,
        "bdi": bdi,
        "table_data": table_data,
        "collected_at": datetime.now().isoformat()
    }


def format_supply_chain_table(shipping_data: dict) -> dict:
    """转化为期刊supplyChain板块格式"""
    return {
        "title": "海运运价指数",
        "data": shipping_data.get("table_data", [])
    }


if __name__ == "__main__":
    data = collect_all_shipping()
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))

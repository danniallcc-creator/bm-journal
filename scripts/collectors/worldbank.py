"""World Bank 基础经济数据采集器 (v3 - 最优批量)
覆盖: GDP/人口/城市化率/CPI通胀 等年度指标
策略: 每个指标1次请求, 包含全部25个国家 = 6次请求, ~10秒完成
API: https://api.worldbank.org/v2/ (免费, 无需Key)
"""
import json, time
from datetime import datetime
from ..config import COUNTRIES, WB_INDICATORS
from ..utils import fetch_json, cache_get, cache_set, save_raw, log, safe_float, fmt_number, pct_change

WB_BASE = "https://api.worldbank.org/v2"
ALL_COUNTRY_CODES = ";".join(COUNTRIES.keys())


def _wb_indicator_all_countries(indicator_id: str) -> dict:
    """一个指标, 所有国家, 一次请求
    Returns: {country_code: [{"date": "2024", "value": 123.4}, ...]}
    """
    url = f"{WB_BASE}/country/{ALL_COUNTRY_CODES}/indicator/{indicator_id}"
    all_records = {}
    page = 1
    total_pages = 1

    while page <= total_pages:
        params = {
            "format": "json",
            "per_page": 200,
            "page": page,
            "date": "2018:2025"
        }
        data = fetch_json(url, params=params, timeout=45, retries=2)
        if not data or not isinstance(data, list) or len(data) < 2:
            break

        meta = data[0]
        # 检查是否有错误消息
        if "message" in meta:
            log.warning(f"WB API error for {indicator_id}: {meta['message']}")
            break

        total_pages = meta.get("pages", 1)
        records = data[1] if isinstance(data[1], list) else []

        for r in records:
            cc = r.get("country", {}).get("id", "")
            if cc not in COUNTRIES:
                continue
            val = safe_float(r.get("value"))
            all_records.setdefault(cc, []).append({
                "date": r.get("date", ""),
                "value": val,
            })

        page += 1
        if page <= total_pages:
            time.sleep(0.5)

    # 每个国家的数据按日期降序
    for cc in all_records:
        all_records[cc].sort(key=lambda x: x["date"], reverse=True)

    return all_records


def collect_all_countries() -> dict:
    """采集所有国家的World Bank数据 (6次请求完成)

    Returns:
        {
            "collected_at": "...",
            "countries": {"CN": {...}, ...},
            "stats": {"total": 25, "ok": 22, "partial": 3, "failed": 0}
        }
    """
    log.info("=== Collecting World Bank data (optimized bulk) ===")

    cache_key = "wb_all_v3"
    cached = cache_get(cache_key, "worldbank", ttl=3600 * 24)
    if cached:
        log.info("Using cached World Bank data")
        return cached

    # 每个指标一次批量请求
    raw_by_indicator = {}
    for ind_key, ind_id in WB_INDICATORS.items():
        log.info(f"  Fetching {ind_key} ({ind_id})...")
        raw_by_indicator[ind_key] = _wb_indicator_all_countries(ind_id)
        count = sum(1 for v in raw_by_indicator[ind_key].values()
                    if any(d["value"] is not None for d in v))
        log.info(f"    → {count} countries with data")
        time.sleep(0.5)

    # 按国家聚合
    countries = {}
    stats = {"total": len(COUNTRIES), "ok": 0, "partial": 0, "failed": 0}

    for cc, info in COUNTRIES.items():
        indicators = {}
        ok_count = 0

        for ind_key in WB_INDICATORS:
            data = raw_by_indicator[ind_key].get(cc, [])
            valid = [d for d in data if d["value"] is not None]
            if valid:
                latest = valid[0]
                previous = valid[1] if len(valid) > 1 else None
                indicators[ind_key] = {
                    "latest": latest,
                    "previous": previous,
                    "change_pct": pct_change(latest["value"], previous["value"]) if previous else None,
                    "history": valid[:5]
                }
                ok_count += 1
            else:
                indicators[ind_key] = {"latest": None, "previous": None, "change_pct": None, "history": []}

        status = "ok" if ok_count == len(WB_INDICATORS) else ("partial" if ok_count > 0 else "failed")
        stats[status] = stats.get(status, 0) + 1

        countries[cc] = {
            "code": cc,
            "name_zh": info["zh"],
            "region": info["region"],
            "indicators": indicators,
            "status": status,
            "collected_at": datetime.now().isoformat()
        }
        save_raw("worldbank", cc, countries[cc])

    output = {
        "collected_at": datetime.now().isoformat(),
        "countries": countries,
        "stats": stats
    }
    save_raw("worldbank", "all_countries", output)
    cache_set(cache_key, "worldbank", output)
    log.info(f"World Bank: {stats['ok']} ok, {stats['partial']} partial, {stats['failed']} failed")
    return output


def format_country_metrics(wb_data: dict) -> dict:
    """将World Bank数据转化为期刊 country card 的 metrics 格式"""
    results = {}

    for code, cd in wb_data.get("countries", {}).items():
        if cd["status"] == "failed":
            continue

        ind = cd["indicators"]
        metrics = []

        gdp_g = ind.get("gdp_growth", {})
        if gdp_g.get("latest") and gdp_g["latest"].get("value") is not None:
            metrics.append({
                "label": "GDP增速",
                "value": f"{gdp_g['latest']['value']:.1f}%",
                "change": gdp_g.get("change_pct")
            })

        pop = ind.get("population", {})
        if pop.get("latest") and pop["latest"].get("value"):
            metrics.append({
                "label": "人口",
                "value": fmt_number(pop["latest"]["value"]),
                "change": pop.get("change_pct")
            })

        urb = ind.get("urbanization", {})
        if urb.get("latest") and urb["latest"].get("value") is not None:
            metrics.append({
                "label": "城市化率",
                "value": f"{urb['latest']['value']:.1f}%",
                "change": urb.get("change_pct")
            })

        cpi = ind.get("cpi_inflation", {})
        if cpi.get("latest") and cpi["latest"].get("value") is not None:
            metrics.append({
                "label": "CPI通胀",
                "value": f"{cpi['latest']['value']:.1f}%",
                "change": cpi.get("change_pct")
            })

        data_year = gdp_g["latest"].get("date", "") if gdp_g.get("latest") else ""

        gdp_nom = ind.get("gdp_nominal", {})
        gdp_str = fmt_number(gdp_nom["latest"]["value"]) if gdp_nom.get("latest") and gdp_nom["latest"].get("value") else "N/A"

        results[code] = {
            "name": cd["name_zh"],
            "flag": "",
            "metrics": metrics,
            "comment": f"World Bank(截至{data_year}年)。GDP: {gdp_str}。",
            "data_year": data_year,
            "source": "World Bank"
        }

    return results


if __name__ == "__main__":
    data = collect_all_countries()
    metrics = format_country_metrics(data)
    print(f"\nTotal countries with data: {len(metrics)}")
    for code in ["US", "CN", "IN", "DE", "BR"]:
        m = metrics.get(code)
        if m:
            print(f"\n--- {m['name']} ---")
            for metric in m["metrics"]:
                chg = ""
                if metric.get("change") is not None:
                    sign = "+" if metric["change"] > 0 else ""
                    chg = f" ({sign}{metric['change']}%)"
                print(f"  {metric['label']}: {metric['value']}{chg}")

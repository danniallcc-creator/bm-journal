"""央行利率采集器
覆盖: Fed(美)/ECB(欧)/BOE(英)/BOJ(日)/PBOC(中)/RBA(澳)/BOC(加)/BCB(巴西)/RBI(印度)/BOK(韩)
数据源: FRED API (primary), ECB SDW (fallback for ECB)
"""
import json
from datetime import datetime, timedelta
from ..config import FRED_API_KEY, CENTRAL_BANK_RATES
from ..utils import fetch_json, cache_get, cache_set, save_raw, log, safe_float, pct_change

FRED_BASE = "https://api.stlouisfed.org/fred"


def _fred_series(series_id: str, sort_order: str = "desc",
                 limit: int = 10, start_date: str = None) -> list[dict]:
    """获取FRED时序数据
    Returns: [{"date": "YYYY-MM-DD", "value": float|None}, ...]
    """
    if not FRED_API_KEY:
        log.warning("FRED_API_KEY not set, skipping FRED fetch")
        return []

    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": sort_order,
        "limit": limit,
    }
    if start_date:
        params["observation_start"] = start_date

    data = fetch_json(f"{FRED_BASE}/series/observations", params=params)
    if not data or "observations" not in data:
        return []

    results = []
    for obs in data["observations"]:
        val = safe_float(obs.get("value"))
        results.append({"date": obs["date"], "value": val})
    return results


def _fred_series_info(series_id: str) -> dict:
    """获取FRED series元信息(标题、频率、单位等)"""
    if not FRED_API_KEY:
        return {}
    data = fetch_json(f"{FRED_BASE}/series", params={
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json"
    })
    if data and "seriess" in data and data["seriess"]:
        s = data["seriess"][0]
        return {
            "title": s.get("title", ""),
            "frequency": s.get("frequency", ""),
            "units": s.get("units", ""),
            "seasonal_adjustment": s.get("seasonal_adjustment", ""),
            "last_updated": s.get("last_updated", ""),
        }
    return {}


def collect_single_bank(key: str, config: dict) -> dict:
    """采集单个央行的利率数据

    Returns:
        {
            "name": "美联储(Fed)",
            "country": "US",
            "current_rate": 5.33,
            "previous_rate": 5.33,
            "change_bps": 0,
            "last_date": "2025-06-12",
            "history": [{"date": "2025-06-12", "value": 5.33}, ...],
            "series_info": {...},
            "status": "ok" | "no_key" | "fetch_failed" | "no_data"
        }
    """
    name = config["name"]
    fred_id = config["fred_id"]
    result = {
        "name": name,
        "fred_id": fred_id,
        "current_rate": None,
        "previous_rate": None,
        "change_bps": None,
        "last_date": None,
        "history": [],
        "series_info": {},
        "status": "ok"
    }

    # 检查缓存
    cached = cache_get(f"cb_{fred_id}", "central_bank")
    if cached:
        log.info(f"Cache hit: {name}")
        return cached

    # FRED采集
    if not FRED_API_KEY:
        result["status"] = "no_key"
        return result

    observations = _fred_series(fred_id, limit=20)
    if not observations:
        result["status"] = "no_data"
        log.warning(f"No data for {name} ({fred_id})")
        return result

    # 过滤有效值
    valid = [o for o in observations if o["value"] is not None]
    if not valid:
        result["status"] = "no_data"
        return result

    result["history"] = valid
    result["current_rate"] = valid[0]["value"]
    result["last_date"] = valid[0]["date"]

    if len(valid) >= 2:
        result["previous_rate"] = valid[1]["value"]
        if valid[1]["value"] is not None and valid[0]["value"] is not None:
            result["change_bps"] = round(
                (valid[0]["value"] - valid[1]["value"]) * 100, 1
            )

    # 获取series元信息
    result["series_info"] = _fred_series_info(fred_id)

    cache_set(f"cb_{fred_id}", "central_bank", result)
    log.info(f"Collected {name}: {result['current_rate']}% (change: {result['change_bps']}bps)")
    return result


def collect_all_central_banks() -> dict:
    """采集所有央行利率

    Returns:
        {
            "collected_at": "2025-06-15T16:00:00",
            "banks": {
                "US": {...},
                "ECB": {...},
                ...
            },
            "summary": "美联储维持5.33%不变; ECB降至3.50%...",
            "status": "ok" | "partial" | "failed"
        }
    """
    log.info("=== Collecting central bank rates ===")
    banks = {}
    ok_count = 0
    fail_count = 0

    for key, config in CENTRAL_BANK_RATES.items():
        result = collect_single_bank(key, config)
        banks[key] = result
        if result["status"] == "ok":
            ok_count += 1
        else:
            fail_count += 1

    # 生成摘要
    summary_parts = []
    for key, b in banks.items():
        if b["status"] == "ok" and b["current_rate"] is not None:
            rate_str = f"{b['current_rate']:.2f}%"
            if b["change_bps"] and abs(b["change_bps"]) > 0.01:
                direction = "加息" if b["change_bps"] > 0 else "降息"
                summary_parts.append(f"{b['name']}: {rate_str} ({direction}{abs(b['change_bps'])}bps)")
            else:
                summary_parts.append(f"{b['name']}: {rate_str} (维持)")

    output = {
        "collected_at": datetime.now().isoformat(),
        "banks": banks,
        "summary": "; ".join(summary_parts[:6]),
        "status": "ok" if fail_count == 0 else ("partial" if ok_count > 0 else "failed"),
        "stats": {"total": len(CENTRAL_BANK_RATES), "ok": ok_count, "failed": fail_count}
    }

    save_raw("central_bank", "all_rates", output)
    log.info(f"Central bank collection: {ok_count} ok, {fail_count} failed")
    return output


def collect_fed_detail() -> dict:
    """美联储深度数据: 利率 + 点阵图预期 + 缩表进度
    点阵图数据需人工维护(FRED无此数据), 此处仅采集利率和资产负债表
    """
    log.info("=== Collecting Fed detailed data ===")

    # 联邦基金有效利率
    fed_rate = collect_single_bank("US", CENTRAL_BANK_RATES["US"])

    # 资产负债表规模(缩表进度)
    balance_sheet = _fred_series("WALCL", limit=10)  # 总资产(百万美元)

    # 通胀预期(5年期盈亏平衡)
    breakeven_5y = _fred_series("T5YIE", limit=5)

    # 10Y国债(利率传导参考)
    treasury_10y = _fred_series("DGS10", limit=5)

    output = {
        "fed_rate": fed_rate,
        "balance_sheet": balance_sheet[:5] if balance_sheet else [],
        "breakeven_5y": breakeven_5y[:3] if breakeven_5y else [],
        "treasury_10y": treasury_10y[:3] if treasury_10y else [],
        "collected_at": datetime.now().isoformat()
    }

    save_raw("central_bank", "fed_detail", output)
    return output


def format_macro_article(fed_data: dict, all_banks: dict) -> dict:
    """将央行数据转化为期刊宏观文章格式

    Returns: 适配 index.html macro 板块的 article 对象
    """
    fed = fed_data.get("fed_rate", {})
    rate = fed.get("current_rate")
    change = fed.get("change_bps")

    if rate is None:
        return {
            "tag": "央行政策",
            "title": "央行利率数据暂不可用",
            "summary": "FRED API Key未配置或数据获取失败。请检查配置。",
            "source": "FRED",
            "link": "https://fred.stlouisfed.org/series/FEDFUNDS",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "impact": 0
        }

    # 构建标题和摘要
    if change and abs(change) > 0.01:
        direction = "加息" if change > 0 else "降息"
        title = f"美联储{direction}{abs(change)}bps至{rate:.2f}%"
    else:
        title = f"美联储维持利率{rate:.2f}%不变"

    # 全球利率环境摘要
    bank_summaries = []
    for key, b in all_banks.get("banks", {}).items():
        if b["status"] == "ok" and b["current_rate"] is not None and key != "US":
            bank_summaries.append(f"{b['name']} {b['current_rate']:.2f}%")

    global_summary = "; ".join(bank_summaries[:5]) if bank_summaries else "全球央行数据待更新"

    # 影响评估
    impact = 3  # 默认中等
    if change and abs(change) >= 50:
        impact = 5  # 大幅变动
    elif change and abs(change) >= 25:
        impact = 4  # 标准幅度变动

    return {
        "tag": "央行政策",
        "title": title,
        "summary": f"联邦基金有效利率{rate:.2f}%。"
                   f"10年期国债收益率{next((t.get('value','N/A') for t in fed_data.get('treasury_10y',[])), 'N/A')}%。"
                   f"全球央行: {global_summary}。"
                   f"对建材行业影响: 利率变动通过房贷利率和建筑融资成本传导至房地产投资和新开工。",
        "source": "FRED / 各国央行",
        "link": "https://fred.stlouisfed.org/series/FEDFUNDS",
        "date": fed.get("last_date", datetime.now().strftime("%Y-%m-%d")),
        "impact": impact
    }


if __name__ == "__main__":
    all_banks = collect_all_central_banks()
    fed_detail = collect_fed_detail()
    article = format_macro_article(fed_detail, all_banks)
    print(json.dumps(article, ensure_ascii=False, indent=2))

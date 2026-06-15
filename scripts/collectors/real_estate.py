"""美国房地产数据采集器
覆盖: Case-Shiller房价指数/建筑许可证/新屋开工/成屋销售/库存/房贷利率
数据源: FRED API (免费, 120次/分钟, CORS支持)
"""
import json
from datetime import datetime
from ..config import FRED_API_KEY, FRED_SERIES
from ..utils import fetch_json, cache_get, cache_set, save_raw, log, safe_float, pct_change

FRED_BASE = "https://api.stlouisfed.org/fred"


def _fred(series_id: str, limit: int = 24, sort_order: str = "desc") -> list[dict]:
    """FRED API请求封装"""
    if not FRED_API_KEY:
        log.warning(f"FRED_API_KEY not set, skipping {series_id}")
        return []
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": sort_order,
        "limit": limit,
    }
    data = fetch_json(f"{FRED_BASE}/series/observations", params=params)
    if not data or "observations" not in data:
        return []
    return [{"date": o["date"], "value": safe_float(o.get("value"))}
            for o in data["observations"]]


def _latest_valid(observations: list, n: int = 1) -> dict | None:
    """取最近n个有效值的最新一个"""
    valid = [o for o in observations if o["value"] is not None]
    return valid[n - 1] if len(valid) >= n else None


def _compute_change(observations: list) -> tuple:
    """计算MoM和YoY变化
    Returns: (current_value, mom_change, yoy_change, last_date)
    """
    valid = [o for o in observations if o["value"] is not None]
    if not valid:
        return None, None, None, None

    current = valid[0]
    # MoM (月度数据: 第2个有效值)
    mom = None
    if len(valid) >= 2:
        mom = pct_change(current["value"], valid[1]["value"])
    # YoY (月度数据: 第13个有效值 ≈ 12个月前)
    yoy = None
    if len(valid) >= 13:
        yoy = pct_change(current["value"], valid[12]["value"])

    return current["value"], mom, yoy, current["date"]


# ==================== 采集函数 ====================

def collect_case_shiller() -> dict:
    """Case-Shiller 全美房价指数
    - 全美指数(季调)
    - 全美同比
    - 20城综合
    - 主要城市单独指数
    """
    log.info("=== Collecting Case-Shiller Home Price Index ===")

    cache_key = "cs_home_price"
    cached = cache_get(cache_key, "real_estate", ttl=3600 * 24)
    if cached:
        return cached

    # 全美指数
    national = _fred(FRED_SERIES["cs_national_sa"], limit=24)
    nat_val, nat_mom, nat_yoy, nat_date = _compute_change(national)

    # 20城综合
    city20 = _fred(FRED_SERIES["cs_20city"], limit=24)
    c20_val, c20_mom, c20_yoy, c20_date = _compute_change(city20)

    # 主要城市 (部分FRED有数据)
    metro_series = {
        "洛杉矶": "LXXRSA",
        "纽约": "NYXRSA",
        "旧金山": "SFXRSA",
        "迈阿密": "MIXRSA",
        "达拉斯": "DAXRSA",
        "西雅图": "SEXRSA",
        "芝加哥": "CHXRSA",
        "亚特兰大": "ATXRSA",
    }
    metros = {}
    for city_name, sid in metro_series.items():
        data = _fred(sid, limit=12)
        val, mom, yoy, date = _compute_change(data)
        if val is not None:
            metros[city_name] = {
                "value": val, "mom": mom, "yoy": yoy, "date": date
            }

    result = {
        "national": {
            "index": nat_val, "mom": nat_mom, "yoy": nat_yoy, "date": nat_date
        },
        "city20": {
            "index": c20_val, "mom": c20_mom, "yoy": c20_yoy, "date": c20_date
        },
        "metros": metros,
        "history_national": national[:12],
        "collected_at": datetime.now().isoformat(),
        "status": "ok" if nat_val else "no_data"
    }

    cache_set(cache_key, "real_estate", result)
    save_raw("real_estate", "case_shiller", result)
    log.info(f"Case-Shiller: National {nat_val} (MoM {nat_mom}%, YoY {nat_yoy}%)")
    return result


def collect_construction_indicators() -> dict:
    """建筑活动先行指标
    - 建筑许可证 (PERMIT)
    - 新屋开工 (HOUST)
    - 建筑支出 (TLACONS)
    - 成屋销售 (EXHOSLUSM495S)
    - 成屋库存月数 (MSACSR)
    - 新房销售 (HSN1FNSA)
    """
    log.info("=== Collecting US construction indicators ===")

    cache_key = "us_construction"
    cached = cache_get(cache_key, "real_estate", ttl=3600 * 12)
    if cached:
        return cached

    indicators = {}

    # 建筑许可证
    permits = _fred(FRED_SERIES["building_permits"], limit=24)
    p_val, p_mom, p_yoy, p_date = _compute_change(permits)
    indicators["permits"] = {
        "label": "建筑许可证", "unit": "千套(SAAR)",
        "value": p_val, "mom": p_mom, "yoy": p_yoy, "date": p_date,
        "history": permits[:12]
    }

    # 新屋开工
    starts = _fred(FRED_SERIES["housing_starts"], limit=24)
    s_val, s_mom, s_yoy, s_date = _compute_change(starts)
    indicators["housing_starts"] = {
        "label": "新屋开工", "unit": "千套(SAAR)",
        "value": s_val, "mom": s_mom, "yoy": s_yoy, "date": s_date,
        "history": starts[:12]
    }

    # 建筑支出
    spending = _fred(FRED_SERIES["construction_spending"], limit=24)
    sp_val, sp_mom, sp_yoy, sp_date = _compute_change(spending)
    indicators["construction_spending"] = {
        "label": "建筑支出", "unit": "十亿美元(SA)",
        "value": sp_val, "mom": sp_mom, "yoy": sp_yoy, "date": sp_date,
        "history": spending[:12]
    }

    # 成屋销售
    existing = _fred(FRED_SERIES["existing_home_sales"], limit=24)
    e_val, e_mom, e_yoy, e_date = _compute_change(existing)
    indicators["existing_home_sales"] = {
        "label": "成屋销售", "unit": "万套(SAAR)",
        "value": e_val, "mom": e_mom, "yoy": e_yoy, "date": e_date,
        "history": existing[:12]
    }

    # 成屋库存月数
    inventory = _fred(FRED_SERIES["existing_home_inventory"], limit=12)
    inv_latest = _latest_valid(inventory)
    inv_prev = _latest_valid(inventory, 2)
    indicators["existing_home_inventory"] = {
        "label": "成屋库存", "unit": "月",
        "value": inv_latest["value"] if inv_latest else None,
        "mom": pct_change(inv_latest["value"], inv_prev["value"])
               if inv_latest and inv_prev else None,
        "date": inv_latest["date"] if inv_latest else None,
    }

    # 新房销售
    new_sales = _fred(FRED_SERIES["new_home_sales"], limit=24)
    n_val, n_mom, n_yoy, n_date = _compute_change(new_sales)
    indicators["new_home_sales"] = {
        "label": "新房销售", "unit": "千套(SA)",
        "value": n_val, "mom": n_mom, "yoy": n_yoy, "date": n_date,
        "history": new_sales[:12]
    }

    result = {
        "indicators": indicators,
        "collected_at": datetime.now().isoformat(),
        "status": "ok"
    }

    cache_set(cache_key, "real_estate", result)
    save_raw("real_estate", "construction_indicators", result)
    log.info(f"Construction: Permits {p_val}K, Starts {s_val}K, Inventory {indicators['existing_home_inventory']['value']}月")
    return result


def collect_mortgage_rates() -> dict:
    """房贷利率 (30Y/15Y固定 + 10Y国债)
    直接传导: 10Y国债 → 30Y房贷 → 购房可负担性 → 新房需求 → 建材
    """
    log.info("=== Collecting mortgage rates ===")

    cache_key = "mortgage_rates"
    cached = cache_get(cache_key, "real_estate", ttl=3600 * 12)
    if cached:
        return cached

    m30 = _fred(FRED_SERIES["us_30y_mortgage"], limit=12)
    m15 = _fred(FRED_SERIES["us_15y_mortgage"], limit=12)
    t10y = _fred(FRED_SERIES["us_10y_treasury"], limit=12)

    def _extract(obs_list):
        latest = _latest_valid(obs_list)
        prev = _latest_valid(obs_list, 2)
        year_ago = _latest_valid(obs_list, 52) if len(obs_list) >= 52 else None
        return {
            "current": latest["value"] if latest else None,
            "previous": prev["value"] if prev else None,
            "date": latest["date"] if latest else None,
            "change_wow": pct_change(latest["value"], prev["value"])
                          if latest and prev else None,
            "history": obs_list[:12]
        }

    result = {
        "mortgage_30y": _extract(m30),
        "mortgage_15y": _extract(m15),
        "treasury_10y": _extract(t10y),
        "collected_at": datetime.now().isoformat(),
        "status": "ok"
    }

    cache_set(cache_key, "real_estate", result)
    save_raw("real_estate", "mortgage_rates", result)
    m30v = result["mortgage_30y"]["current"]
    log.info(f"Mortgage: 30Y={m30v}%, 15Y={result['mortgage_15y']['current']}%, 10Y={result['treasury_10y']['current']}%")
    return result


def collect_commodity_prices() -> dict:
    """建材相关大宗商品价格 (FRED可用部分)
    铁矿石/铝/铜/锌/天然气/煤炭/原油
    """
    log.info("=== Collecting commodity prices from FRED ===")

    cache_key = "commodities"
    cached = cache_get(cache_key, "real_estate", ttl=3600 * 6)
    if cached:
        return cached

    commodity_keys = [
        ("iron_ore", "铁矿石", "$/mt"),
        ("aluminum_price", "铝", "$/mt"),
        ("copper_price", "铜", "$/mt"),
        ("zinc_price", "锌", "$/mt"),
        ("lead_price", "铅", "$/mt"),
        ("nickel_price", "镍", "$/mt"),
        ("natural_gas_hh", "天然气(HH)", "$/MMBtu"),
        ("wti_crude", "WTI原油", "$/barrel"),
        ("brent_crude", "Brent原油", "$/barrel"),
        ("coal", "动力煤", "$/mt"),
    ]

    items = {}
    for key, label, unit in commodity_keys:
        sid = FRED_SERIES.get(key)
        if not sid:
            continue
        obs = _fred(sid, limit=12)
        val, mom, yoy, date = _compute_change(obs)
        if val is not None:
            items[label] = {
                "value": val, "unit": unit,
                "mom": mom, "yoy": yoy, "date": date,
                "history": obs[:6]
            }
        log.info(f"  {label}: {val} {unit} (MoM: {mom}%)")

    result = {
        "items": items,
        "collected_at": datetime.now().isoformat(),
        "status": "ok" if items else "no_data"
    }

    cache_set(cache_key, "real_estate", result)
    save_raw("real_estate", "commodity_prices", result)
    return result


def collect_all_us_real_estate() -> dict:
    """汇总所有美国房地产数据"""
    log.info("=== Collecting all US real estate data ===")
    return {
        "case_shiller": collect_case_shiller(),
        "construction": collect_construction_indicators(),
        "mortgage": collect_mortgage_rates(),
        "commodities": collect_commodity_prices(),
        "collected_at": datetime.now().isoformat()
    }


def format_us_country_card(us_data: dict) -> dict:
    """将美国数据转化为期刊 country card 格式"""
    cs = us_data.get("case_shiller", {})
    cons = us_data.get("construction", {}).get("indicators", {})
    mort = us_data.get("mortgage", {})

    metrics = []

    # 房价 (Case-Shiller YoY)
    nat = cs.get("national", {})
    if nat.get("yoy") is not None:
        metrics.append({
            "label": "Case-Shiller房价(YoY)",
            "value": f"{nat['yoy']:.1f}%",
            "change": nat["yoy"]
        })

    # 新房开工
    starts = cons.get("housing_starts", {})
    if starts.get("value"):
        metrics.append({
            "label": "新屋开工",
            "value": f"{starts['value']:.0f}千套",
            "change": starts.get("yoy")
        })

    # 建筑许可证
    permits = cons.get("permits", {})
    if permits.get("value"):
        metrics.append({
            "label": "建筑许可证",
            "value": f"{permits['value']:.0f}千套",
            "change": permits.get("yoy")
        })

    # 30Y房贷利率
    m30 = mort.get("mortgage_30y", {})
    if m30.get("current"):
        metrics.append({
            "label": "30Y房贷利率",
            "value": f"{m30['current']:.2f}%",
            "change": m30.get("change_wow")
        })

    # 成屋库存月数
    inv = cons.get("existing_home_inventory", {})
    if inv.get("value"):
        metrics.append({
            "label": "成屋库存",
            "value": f"{inv['value']:.1f}月",
            "change": inv.get("mom")
        })

    # 建筑支出
    spending = cons.get("construction_spending", {})
    if spending.get("value"):
        metrics.append({
            "label": "建筑支出",
            "value": f"${spending['value']:.0f}B",
            "change": spending.get("yoy")
        })

    # 生成分析评语
    comment_parts = []
    if nat.get("yoy") is not None:
        if nat["yoy"] > 0:
            comment_parts.append(f"房价同比上涨{nat['yoy']:.1f}%")
        else:
            comment_parts.append(f"房价同比下降{abs(nat['yoy']):.1f}%")
    if starts.get("yoy") is not None:
        comment_parts.append(f"新屋开工同比{'增长' if starts['yoy'] > 0 else '下降'}{abs(starts['yoy']):.1f}%")
    if m30.get("current"):
        comment_parts.append(f"30Y房贷{m30['current']:.2f}%")

    return {
        "name": "美国",
        "flag": "",
        "metrics": metrics,
        "comment": "，".join(comment_parts) + "。",
        "source": "FRED / Case-Shiller / Census Bureau",
        "data_date": nat.get("date", "")
    }


if __name__ == "__main__":
    data = collect_all_us_real_estate()
    card = format_us_country_card(data)
    print(json.dumps(card, ensure_ascii=False, indent=2))

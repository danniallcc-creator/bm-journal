"""中国海关月度出口数据采集器 (基于UN Comtrade月度API)
数据源: UN Comtrade v1 API (https://comtradeapi.un.org/data/v1/get)
覆盖: 24个建材二级品类 × 207个HS编码 × 235个贸易伙伴国
频率: 月度 (数据延迟约2-3个月)
需要: UN_COMTRADE_KEY 环境变量 (免费注册: comtradedeveloper.un.org)
"""
import json, os, time
from datetime import datetime, timedelta
from collections import defaultdict
from ..utils import fetch_json, cache_get, cache_set, save_raw, log, safe_float, pct_change

COMTRADE_KEY = os.environ.get("UN_COMTRADE_KEY", "")
COMTRADE_BASE = "https://comtradeapi.un.org/data/v1/get/C/M/HS"

# API配额状态 (模块级,防止403时级联重试)
_api_quota_exceeded = False

# ===== 完整24品类 × 207 HS编码映射 (来源: 建材-hs编码大全.xlsx) =====
HS_FULL_MAPPING = {
    "土工材料": ["560313"],
    "地板供暖系统及配件": ["732219"],
    "地板及配件": ["391810", "441875", "441874", "391890", "441879", "690490", "441873"],
    "塑料管": ["391722", "391723", "391721"],
    "墙纸/墙板": ["481420"],
    "壁炉、炉灶": ["732190", "732189"],
    "建筑工业玻璃": ["700800", "700729", "701690"],
    "建筑板材": [
        "441241", "441892", "441239", "441233", "441231", "441012", "441039",
        "441294", "441299", "441011", "441292", "441291", "441293", "441234",
        "441232", "441242", "441031", "441033", "441032", "680911", "680919",
        "681011", "681012", "681019"
    ],
    "木材": [
        "440398", "440795", "440796", "440395", "440396", "440397", "440394",
        "440399", "440391", "440392", "440393", "440321", "440322", "440323",
        "440324", "440325", "440326", "440341", "440349", "440711", "440712",
        "440719", "440721", "440722", "440723", "440724", "440725", "440726",
        "440727", "440728", "440729", "440791", "440792", "440793", "440794",
        "440797", "440799", "440810", "440831", "440839", "440890", "440910",
        "440921", "440922", "440929", "441210", "441231", "441232", "441233",
        "441234", "441239", "441241", "441242", "441291", "441292", "441293",
        "441294", "441299", "441300", "441400", "441600", "441700", "441890",
        "441520"
    ],
    "栏杆与扶手": ["730120"],
    "梯子及脚手架": ["730840"],
    "模架": ["441840"],
    "活动房屋与钢结构": ["940610", "940620", "940690"],
    "浴室和厨房产品": [
        "732410", "940340", "691010", "848190", "761520", "691090", "741999",
        "732490", "392490", "940360", "940330"
    ],
    "瓷砖及配件": [
        "690590", "690740", "690410", "690490", "690510", "690520", "690721",
        "690722", "690723"
    ],
    "电梯和自动扶梯": ["842810", "842840"],
    "石材": [
        "680293", "681019", "680221", "251310", "250860", "251512", "680291",
        "680292", "680299", "680222", "680223", "680229", "251511", "251520",
        "252010", "252020", "252090", "250700", "250810", "250820", "250830",
        "250840", "250850"
    ],
    "砖石材料": [
        "252321", "681181", "252330", "681140", "690310", "252310", "690290",
        "690100", "252329", "252390", "690320", "690390", "690210", "690220",
        "690240", "690290", "381600", "680690", "690710", "680911", "680919",
        "681011", "681012", "681019", "681091", "681099", "681110", "681120",
        "681130", "681140"
    ],
    "金属建材": ["830241"],
    "门、窗及其配件": [
        "441819", "441829", "730830", "830241", "830260", "830249", "830230",
        "830210", "830242", "761010", "761020", "391620", "391610", "441810"
    ],
    "防水材料": ["680710"],
    "防火材料": ["381600", "680690"],
    "隔热材料": ["392111"],
    "马赛克": ["701610", "680210"],
}

# 去重: 某些HS码跨类目复用 → 构建全量唯一HS码列表
ALL_HS_CODES = sorted(set(code for codes in HS_FULL_MAPPING.values() for code in codes))

# === 4位码降级映射 ===
# Comtrade中中国对部分品类只上报4位汇总码 (非6位细码)
# 当6位码查询返回0时, 自动降级使用4位码查询
HS_FALLBACK_4DIGIT = {
    "木材": ["4403", "4407", "4408", "4409", "4412", "4413", "4414", "4415",
             "4416", "4417", "4418"],
    "建筑板材": ["4410", "4412", "6809", "6810"],
    "石材": ["2507", "2508", "2513", "2515", "2520", "6802"],
    "砖石材料": ["2523", "6810", "6811", "6901", "6902", "6903", "6907"],
}

# 中国 Comtrade reporter代码
CHINA_REPORTER = "156"

# 八大区域国家映射 (Comtrade partner codes)
REGION_PARTNERS = {
    "北美": {"840": "美国", "124": "加拿大", "484": "墨西哥"},
    "南美": {"076": "巴西", "152": "智利", "604": "秘鲁", "170": "哥伦比亚",
             "032": "阿根廷", "218": "厄瓜多尔", "862": "委内瑞拉", "858": "乌拉圭",
             "600": "巴拉圭", "068": "玻利维亚", "328": "圭亚那", "740": "苏里南"},
    "西欧": {"826": "英国", "276": "德国", "250": "法国", "380": "意大利",
             "724": "西班牙", "616": "波兰", "528": "荷兰", "056": "比利时"},
    "中东": {"682": "沙特", "784": "阿联酋", "634": "卡塔尔", "512": "阿曼",
             "414": "科威特", "368": "伊拉克", "364": "伊朗", "400": "约旦",
             "376": "以色列", "792": "土耳其", "818": "埃及", "788": "突尼斯",
             "012": "阿尔及利亚", "504": "摩洛哥", "434": "利比亚"},
    "东南亚": {"704": "越南", "360": "印尼", "608": "菲律宾", "764": "泰国",
              "458": "马来西亚", "702": "新加坡", "104": "缅甸", "116": "柬埔寨",
              "418": "老挝", "096": "文莱", "626": "东帝汶"},
    "中亚": {"398": "哈萨克斯坦", "860": "乌兹别克斯坦", "762": "塔吉克斯坦",
             "417": "吉尔吉斯斯坦", "795": "土库曼斯坦", "496": "蒙古"},
    "澳洲": {"036": "澳大利亚", "554": "新西兰", "598": "巴布亚新几内亚", "242": "斐济"},
    "南亚": {"356": "印度", "586": "巴基斯坦", "050": "孟加拉国", "144": "斯里兰卡",
             "524": "尼泊尔", "004": "阿富汗", "462": "马尔代夫"},
    "日韩": {"392": "日本", "410": "韩国"},
}

# 所有partner code列表 (用于批量查询)
ALL_PARTNER_CODES = sorted(set(
    code for region in REGION_PARTNERS.values() for code in region.keys()
))


def _build_period_str(year: int, month: int) -> str:
    """构建Comtrade月度period格式: YYYYMM"""
    return f"{year}{month:02d}"


def _probe_api(period: str) -> bool:
    """快速探测API是否可用 (仅查1个HS码, 不重试)
    Returns: True if API is accessible, False if quota exceeded or error
    """
    global _api_quota_exceeded
    if _api_quota_exceeded:
        return False

    params = {
        "reporterCode": CHINA_REPORTER,
        "period": period,
        "flowCode": "X",
        "cmdCode": "560313",  # 土工材料, 单个HS码
        "includeDesc": "false",
        "subscription-key": COMTRADE_KEY,
    }
    import requests
    try:
        resp = requests.get(COMTRADE_BASE, params=params, timeout=20)
        if resp.status_code == 403:
            _api_quota_exceeded = True
            log.warning("Comtrade API quota exceeded (403), skipping customs collection")
            return False
        if resp.status_code == 200:
            return True
        log.warning(f"Comtrade API probe: HTTP {resp.status_code}")
        return False
    except Exception as e:
        log.warning(f"Comtrade API probe error: {e}")
        return False


def _fetch_monthly_batch(hs_codes: list[str], period: str,
                         partner_codes: list[str] = None) -> list[dict]:
    """批量查询: 中国出口 → 指定HS编码 × 指定伙伴国 × 单月

    Comtrade API支持逗号分隔的多HS码和多partner码 (单次上限约20个cmdCode)
    """
    if not COMTRADE_KEY:
        return []

    # 快速失败: API已知配额耗尽时直接跳过
    if _api_quota_exceeded:
        return []

    params = {
        "reporterCode": CHINA_REPORTER,
        "period": period,
        "flowCode": "X",  # 出口
        "cmdCode": ",".join(hs_codes),
        "includeDesc": "true",
        "subscription-key": COMTRADE_KEY,
    }
    if partner_codes:
        params["partnerCode"] = ",".join(partner_codes)

    url = COMTRADE_BASE
    data = fetch_json(url, params=params, timeout=45, retries=2)

    if not data:
        return []

    # Comtrade v1返回 {"count":N, "data":[...], "error":""}
    if isinstance(data, dict) and "data" in data:
        records = data["data"]
    elif isinstance(data, list):
        records = data
    else:
        log.warning(f"Comtrade unexpected response format for period={period}")
        return []

    results = []
    for item in records:
        val = safe_float(item.get("primaryValue"))
        if val and val > 0:
            results.append({
                "partner_code": str(item.get("partnerCode", "")),
                "partner_name": item.get("partnerDesc", ""),
                "hs_code": str(item.get("cmdCode", "")),
                "cmd_desc": item.get("cmdDesc", ""),
                "value_usd": val,
                "net_wgt_kg": safe_float(item.get("netWgt")),
                "period": period,
            })
    return results


def _chunk_list(lst: list, size: int) -> list[list]:
    """分块工具"""
    return [lst[i:i+size] for i in range(0, len(lst), size)]


def collect_customs_monthly(year: int = None, month: int = None,
                            compare_year: int = None) -> dict:
    """采集中国建材月度出口数据 (当月 + 去年同期用于同比计算)

    Args:
        year/month: 目标月份, 默认取最近可用月份 (当前月-3个月, Comtrade延迟)
        compare_year: 同比对照年份, 默认 year-1

    Returns:
        {
            "period": "202604",
            "compare_period": "202504",
            "categories": {
                "瓷砖及配件": {
                    "current_usd": 123456789,
                    "previous_usd": 100000000,
                    "yoy_pct": 23.5,
                    "by_region": {"北美": {"current": ..., "previous": ..., "yoy": ...}, ...},
                    "top_partners": [{"code":"840","name":"美国","value":...,"yoy":...}, ...]
                }, ...
            },
            "total_current_usd": ...,
            "total_previous_usd": ...,
            "total_yoy_pct": ...,
            "status": "ok"
        }
    """
    log.info("=== Collecting China customs monthly export data ===")

    if not COMTRADE_KEY:
        log.warning("UN_COMTRADE_KEY not set, skipping customs monthly")
        return {"status": "no_key", "categories": {}}

    # 确定目标月份 (默认当前月份-3个月,因Comtrade延迟)
    if year is None or month is None:
        target = datetime.now() - timedelta(days=90)
        year = target.year
        month = target.month
    if compare_year is None:
        compare_year = year - 1

    # 月份回退: 如首选月无数据(Comtrade延迟可达4个月),向前最多退3个月
    _original_year, _original_month = year, month
    for _attempt in range(4):  # 首选月 + 最多退3次
        period_current = _build_period_str(year, month)
        period_previous = _build_period_str(compare_year, month)

        # 缓存检查 (月度数据30天TTL)
        cache_key = f"customs_monthly_{period_current}"
        cached = cache_get(cache_key, "customs_monthly", ttl=3600 * 24 * 30)
        if cached:
            if cached.get("total_current_usd", 0) > 0:
                log.info(f"Customs monthly {period_current}: using cache (has data)")
                return cached
            else:
                log.info(f"Customs monthly {period_current}: cache shows 0, try earlier month")
                # 退一个月
                if month == 1:
                    month = 12
                    year -= 1
                    compare_year -= 1
                else:
                    month -= 1
                continue

        log.info(f"Fetching: China exports {period_current} vs {period_previous} (attempt {_attempt+1})")
        break
    else:
        # 4次回退后仍为缓存0值,使用最后一个period继续尝试在线获取
        period_current = _build_period_str(year, month)
        period_previous = _build_period_str(compare_year, month)
        cache_key = f"customs_monthly_{period_current}"
        log.info(f"Fetching: China exports {period_current} vs {period_previous} (final fallback)")
    log.info(f"Categories: {len(HS_FULL_MAPPING)}, HS codes: {len(ALL_HS_CODES)}")

    # API可用性探测 (防止403配额耗尽时级联重试)
    if not _probe_api(period_current):
        log.warning(f"Comtrade API unavailable for {period_current}, returning empty result")
        return {
            "period": period_current,
            "compare_period": period_previous,
            "year": year,
            "month": month,
            "categories": {},
            "total_current_usd": 0,
            "total_previous_usd": 0,
            "total_yoy_pct": None,
            "categories_count": 0,
            "hs_codes_count": len(ALL_HS_CODES),
            "collected_at": datetime.now().isoformat(),
            "status": "api_unavailable",
        }

    # 按品类逐批采集 (每个品类的HS码一次性查询,分块≤20个)
    categories_result = {}
    total_current = 0
    total_previous = 0

    for category, hs_codes in HS_FULL_MAPPING.items():
        log.info(f"  {category} ({len(hs_codes)} codes)...")
        cat_current_total = 0
        cat_previous_total = 0
        # 按partner×period汇总
        partner_current = defaultdict(float)  # partner_code → USD
        partner_previous = defaultdict(float)

        # 分块查询 (Comtrade单次最多约20个cmdCode)
        hs_chunks = _chunk_list(hs_codes, 20)

        for chunk in hs_chunks:
            # 当期数据
            records = _fetch_monthly_batch(chunk, period_current)
            for rec in records:
                val = rec["value_usd"]
                cat_current_total += val
                partner_current[rec["partner_code"]] += val

            time.sleep(0.5)  # 限流

            # 同期数据
            records_prev = _fetch_monthly_batch(chunk, period_previous)
            for rec in records_prev:
                val = rec["value_usd"]
                cat_previous_total += val
                partner_previous[rec["partner_code"]] += val

            time.sleep(0.5)

        # 4位码降级: 如果6位码无数据,尝试4位码
        if cat_current_total == 0 and category in HS_FALLBACK_4DIGIT:
            fallback_codes = HS_FALLBACK_4DIGIT[category]
            log.info(f"    ↳ Fallback to 4-digit codes: {fallback_codes}")
            fb_chunks = _chunk_list(fallback_codes, 20)
            for chunk in fb_chunks:
                records = _fetch_monthly_batch(chunk, period_current)
                for rec in records:
                    cat_current_total += rec["value_usd"]
                    partner_current[rec["partner_code"]] += rec["value_usd"]
                time.sleep(0.5)
                records_prev = _fetch_monthly_batch(chunk, period_previous)
                for rec in records_prev:
                    cat_previous_total += rec["value_usd"]
                    partner_previous[rec["partner_code"]] += rec["value_usd"]
                time.sleep(0.5)

        # 按区域汇总
        by_region = {}
        for region, partners in REGION_PARTNERS.items():
            region_current = sum(partner_current.get(code, 0) for code in partners)
            region_previous = sum(partner_previous.get(code, 0) for code in partners)
            by_region[region] = {
                "current_usd": region_current,
                "previous_usd": region_previous,
                "yoy_pct": pct_change(region_current, region_previous),
            }

        # Top partners (按当期金额排序)
        top_partners = sorted(partner_current.items(), key=lambda x: -x[1])[:15]
        top_partners_data = []
        for code, val in top_partners:
            prev_val = partner_previous.get(code, 0)
            # 查找国家名 (优先从区域映射获取)
            name = ""
            for region_partners in REGION_PARTNERS.values():
                if code in region_partners:
                    name = region_partners[code]
                    break
            top_partners_data.append({
                "code": code,
                "name": name or code,
                "current_usd": val,
                "previous_usd": prev_val,
                "yoy_pct": pct_change(val, prev_val),
            })

        categories_result[category] = {
            "current_usd": cat_current_total,
            "previous_usd": cat_previous_total,
            "yoy_pct": pct_change(cat_current_total, cat_previous_total),
            "by_region": by_region,
            "top_partners": top_partners_data,
        }

        total_current += cat_current_total
        total_previous += cat_previous_total

        time.sleep(1)  # 品类间间隔

    output = {
        "period": period_current,
        "compare_period": period_previous,
        "year": year,
        "month": month,
        "categories": categories_result,
        "total_current_usd": total_current,
        "total_previous_usd": total_previous,
        "total_yoy_pct": pct_change(total_current, total_previous),
        "categories_count": len(categories_result),
        "hs_codes_count": len(ALL_HS_CODES),
        "collected_at": datetime.now().isoformat(),
        "status": "ok",
    }

    # 缓存与存储
    cache_set(cache_key, "customs_monthly", output)
    save_raw("customs_monthly", f"china_exports_{period_current}", output)

    # 如果当期无数据且还有回退余地,尝试前一个月
    # (但如果API配额已耗尽则不重试)
    if (total_current == 0 and not _api_quota_exceeded and (year, month) != (
        _original_year - 1 if _original_month <= 3 else _original_year,
        (_original_month - 4) if _original_month > 4 else (_original_month + 8)
    )):
        prev_month = month - 1 if month > 1 else 12
        prev_year = year if month > 1 else year - 1
        prev_compare_year = prev_year - 1
        log.info(f"Customs monthly {period_current} returned $0 — "
                 f"falling back to {_build_period_str(prev_year, prev_month)}")
        return collect_customs_monthly(
            year=prev_year, month=prev_month, compare_year=prev_compare_year
        )

    log.info(f"Customs monthly complete: {period_current}, "
             f"total=${total_current/1e6:.1f}M, YoY={output['total_yoy_pct']}%")
    return output


def collect_customs_ytd(year: int = None, months: int = None) -> dict:
    """采集年度累计(YTD)数据 — 多月汇总

    Args:
        year: 目标年份, 默认今年
        months: 累计到第几个月, 默认可用最新月(当前-3)
    Returns:
        与 collect_customs_monthly 同结构, period为"YYYY01-YYYYMM"格式
    """
    if year is None:
        year = datetime.now().year
    if months is None:
        # 最新可用月份 (延迟3个月)
        months = max(1, (datetime.now() - timedelta(days=90)).month)

    cache_key = f"customs_ytd_{year}_{months:02d}"
    cached = cache_get(cache_key, "customs_monthly", ttl=3600 * 24 * 30)
    if cached:
        return cached

    log.info(f"=== Collecting customs YTD: {year} M1-M{months} ===")

    if not COMTRADE_KEY:
        return {"status": "no_key", "categories": {}}

    # 构建多月period字符串 (逗号分隔)
    periods_current = ",".join(_build_period_str(year, m) for m in range(1, months + 1))
    periods_previous = ",".join(_build_period_str(year - 1, m) for m in range(1, months + 1))

    categories_result = {}
    total_current = 0
    total_previous = 0

    for category, hs_codes in HS_FULL_MAPPING.items():
        log.info(f"  YTD {category} ({len(hs_codes)} codes)...")
        cat_current = 0
        cat_previous = 0
        partner_current = defaultdict(float)
        partner_previous = defaultdict(float)

        hs_chunks = _chunk_list(hs_codes, 15)  # YTD多月查询量大,每批少一些

        for chunk in hs_chunks:
            # 当年累计
            records = _fetch_monthly_batch(chunk, periods_current)
            for rec in records:
                cat_current += rec["value_usd"]
                partner_current[rec["partner_code"]] += rec["value_usd"]
            time.sleep(0.8)

            # 去年同期累计
            records_prev = _fetch_monthly_batch(chunk, periods_previous)
            for rec in records_prev:
                cat_previous += rec["value_usd"]
                partner_previous[rec["partner_code"]] += rec["value_usd"]
            time.sleep(0.8)

        # 区域汇总
        by_region = {}
        for region, partners in REGION_PARTNERS.items():
            rc = sum(partner_current.get(code, 0) for code in partners)
            rp = sum(partner_previous.get(code, 0) for code in partners)
            by_region[region] = {
                "current_usd": rc,
                "previous_usd": rp,
                "yoy_pct": pct_change(rc, rp),
            }

        # Top partners
        top_partners = sorted(partner_current.items(), key=lambda x: -x[1])[:15]
        top_data = []
        for code, val in top_partners:
            prev_val = partner_previous.get(code, 0)
            name = ""
            for rp in REGION_PARTNERS.values():
                if code in rp:
                    name = rp[code]
                    break
            top_data.append({
                "code": code, "name": name or code,
                "current_usd": val, "previous_usd": prev_val,
                "yoy_pct": pct_change(val, prev_val),
            })

        categories_result[category] = {
            "current_usd": cat_current,
            "previous_usd": cat_previous,
            "yoy_pct": pct_change(cat_current, cat_previous),
            "by_region": by_region,
            "top_partners": top_data,
        }
        total_current += cat_current
        total_previous += cat_previous
        time.sleep(1)

    output = {
        "period": f"{year}01-{year}{months:02d}",
        "compare_period": f"{year-1}01-{year-1}{months:02d}",
        "year": year,
        "months": months,
        "categories": categories_result,
        "total_current_usd": total_current,
        "total_previous_usd": total_previous,
        "total_yoy_pct": pct_change(total_current, total_previous),
        "categories_count": len(categories_result),
        "collected_at": datetime.now().isoformat(),
        "status": "ok",
    }

    cache_set(cache_key, "customs_monthly", output)
    save_raw("customs_monthly", f"china_exports_ytd_{year}_M{months:02d}", output)
    return output


def format_customs_dashboard(data: dict) -> dict:
    """将海关数据转化为前端看板JSON格式

    输出格式:
    {
        "title": "中国建材出口月度看板",
        "period": "2026年4月",
        "summary": {"total": ..., "yoy": ..., "highlights": [...]},
        "categories": [{name, value, yoy, sparkTrend}, ...],
        "regions": [{name, value, yoy, topCategory}, ...],
        "alerts": [{type, message, category, region}, ...]
    }
    """
    if data.get("status") != "ok":
        return {"title": "中国建材出口月度看板", "status": data.get("status", "error")}

    year = data.get("year", 0)
    month = data.get("month", 0)
    period_label = f"{year}年{month}月" if month else data.get("period", "")

    # 品类排名 (按当期金额)
    cat_list = []
    for name, cat_data in data.get("categories", {}).items():
        cat_list.append({
            "name": name,
            "value_usd": cat_data.get("current_usd", 0),
            "previous_usd": cat_data.get("previous_usd", 0),
            "yoy_pct": cat_data.get("yoy_pct"),
        })
    cat_list.sort(key=lambda x: -(x["value_usd"] or 0))

    # 区域汇总
    region_totals = defaultdict(lambda: {"current": 0, "previous": 0})
    for cat_data in data.get("categories", {}).values():
        for region, rdata in cat_data.get("by_region", {}).items():
            region_totals[region]["current"] += rdata.get("current_usd", 0)
            region_totals[region]["previous"] += rdata.get("previous_usd", 0)

    region_list = []
    for region, totals in region_totals.items():
        yoy = pct_change(totals["current"], totals["previous"])
        # 找该区域增长最快的品类
        top_cat = ""
        top_cat_yoy = -999
        for cat_name, cat_data in data.get("categories", {}).items():
            r_info = cat_data.get("by_region", {}).get(region, {})
            r_yoy = r_info.get("yoy_pct")
            if r_yoy is not None and r_yoy > top_cat_yoy and r_info.get("current_usd", 0) > 10000:
                top_cat_yoy = r_yoy
                top_cat = cat_name
        region_list.append({
            "name": region,
            "value_usd": totals["current"],
            "yoy_pct": yoy,
            "top_growth_category": top_cat,
            "top_growth_yoy": top_cat_yoy if top_cat_yoy > -999 else None,
        })
    region_list.sort(key=lambda x: -(x["value_usd"] or 0))

    # 异常预警 (YoY > +50% 或 < -30%)
    alerts = []
    for cat_name, cat_data in data.get("categories", {}).items():
        yoy = cat_data.get("yoy_pct")
        if yoy is not None and cat_data.get("current_usd", 0) > 100000:
            if yoy > 50:
                alerts.append({
                    "type": "surge",
                    "message": f"{cat_name}出口同比激增{yoy:.1f}%",
                    "category": cat_name,
                    "yoy": yoy,
                })
            elif yoy < -30:
                alerts.append({
                    "type": "decline",
                    "message": f"{cat_name}出口同比大幅下滑{yoy:.1f}%",
                    "category": cat_name,
                    "yoy": yoy,
                })

        # 区域级别异常
        for region, rdata in cat_data.get("by_region", {}).items():
            r_yoy = rdata.get("yoy_pct")
            if r_yoy is not None and rdata.get("current_usd", 0) > 50000:
                if r_yoy > 100:
                    alerts.append({
                        "type": "regional_surge",
                        "message": f"{cat_name}→{region} 同比+{r_yoy:.0f}%",
                        "category": cat_name,
                        "region": region,
                        "yoy": r_yoy,
                    })
                elif r_yoy < -50:
                    alerts.append({
                        "type": "regional_decline",
                        "message": f"{cat_name}→{region} 同比{r_yoy:.0f}%",
                        "category": cat_name,
                        "region": region,
                        "yoy": r_yoy,
                    })

    # 只保留最显著的前10个预警
    alerts.sort(key=lambda x: -abs(x.get("yoy", 0)))
    alerts = alerts[:10]

    # 亮点摘要
    highlights = []
    if cat_list:
        top = cat_list[0]
        highlights.append(f"最大品类: {top['name']} ${top['value_usd']/1e6:.1f}M")
    surges = [c for c in cat_list if (c.get("yoy_pct") or 0) > 30]
    if surges:
        highlights.append(f"{len(surges)}个品类同比增长超30%")
    declines = [c for c in cat_list if (c.get("yoy_pct") or 0) < -20]
    if declines:
        highlights.append(f"{len(declines)}个品类同比下滑超20%")

    return {
        "title": "中国建材出口月度看板",
        "period": period_label,
        "summary": {
            "total_usd": data.get("total_current_usd", 0),
            "total_yoy_pct": data.get("total_yoy_pct"),
            "categories_count": data.get("categories_count", 0),
            "highlights": highlights,
        },
        "categories": cat_list,
        "regions": region_list,
        "alerts": alerts,
        "data_source": "UN Comtrade (中国海关总署上报)",
        "data_lag": "约2-3个月",
    }


def format_customs_for_journal(data: dict) -> list[dict]:
    """转化为bm-journal supplyChain板块格式 (兼容现有UI)"""
    if data.get("status") != "ok":
        return []

    tables = []
    period = data.get("period", "")

    # 表1: 品类出口总览
    cat_rows = []
    for name, cat_data in sorted(
        data.get("categories", {}).items(),
        key=lambda x: -(x[1].get("current_usd") or 0)
    ):
        val = cat_data.get("current_usd", 0)
        yoy = cat_data.get("yoy_pct")
        if val > 0:
            cat_rows.append({
                "item": name,
                "value": f"${val/1e6:.1f}M" if val >= 1e6 else f"${val/1e3:.0f}K",
                "change": yoy or 0,
            })

    if cat_rows:
        tables.append({
            "title": f"中国建材出口月度总览 ({period})",
            "data": cat_rows[:15],
        })

    # 表2: 区域同比
    region_rows = []
    region_totals = defaultdict(lambda: {"c": 0, "p": 0})
    for cat_data in data.get("categories", {}).values():
        for region, rdata in cat_data.get("by_region", {}).items():
            region_totals[region]["c"] += rdata.get("current_usd", 0)
            region_totals[region]["p"] += rdata.get("previous_usd", 0)

    for region in ["北美", "西欧", "东南亚", "中东", "南美", "南亚", "澳洲", "中亚", "日韩"]:
        t = region_totals.get(region, {"c": 0, "p": 0})
        if t["c"] > 0:
            yoy = pct_change(t["c"], t["p"])
            region_rows.append({
                "item": region,
                "value": f"${t['c']/1e6:.1f}M" if t["c"] >= 1e6 else f"${t['c']/1e3:.0f}K",
                "change": yoy or 0,
            })

    if region_rows:
        tables.append({
            "title": f"八大区域出口同比 ({period})",
            "data": region_rows,
        })

    return tables


if __name__ == "__main__":
    # 独立测试
    print("Testing customs_monthly collector...")
    print(f"HS codes: {len(ALL_HS_CODES)} unique across {len(HS_FULL_MAPPING)} categories")
    print(f"Partner countries: {len(ALL_PARTNER_CODES)} across {len(REGION_PARTNERS)} regions")

    if COMTRADE_KEY:
        # 测试单月采集
        data = collect_customs_monthly()
        if data.get("status") == "ok":
            dashboard = format_customs_dashboard(data)
            print(f"\nDashboard: {dashboard['period']}")
            print(f"Total: ${dashboard['summary']['total_usd']/1e6:.1f}M")
            print(f"YoY: {dashboard['summary']['total_yoy_pct']}%")
            print(f"\nTop categories:")
            for c in dashboard["categories"][:5]:
                print(f"  {c['name']}: ${c['value_usd']/1e6:.1f}M ({c['yoy_pct']:+.1f}%)")
            print(f"\nAlerts: {len(dashboard['alerts'])}")
            for a in dashboard["alerts"][:3]:
                print(f"  [{a['type']}] {a['message']}")
        else:
            print(f"Status: {data.get('status')}")
    else:
        print("\nUN_COMTRADE_KEY not set. Set it to test data fetching.")
        print("Register free at: https://comtradedeveloper.un.org/")
        print("\nDry run - format test with mock data:")
        mock = {
            "status": "ok", "period": "202604", "year": 2026, "month": 4,
            "total_current_usd": 850000000, "total_previous_usd": 720000000,
            "total_yoy_pct": 18.1, "categories_count": 24,
            "categories": {
                "活动房屋与钢结构": {
                    "current_usd": 320000000, "previous_usd": 250000000,
                    "yoy_pct": 28.0,
                    "by_region": {"北美": {"current_usd": 80000000, "previous_usd": 55000000, "yoy_pct": 45.5}},
                    "top_partners": [{"code": "840", "name": "美国", "current_usd": 60000000, "previous_usd": 40000000, "yoy_pct": 50.0}]
                },
                "瓷砖及配件": {
                    "current_usd": 180000000, "previous_usd": 195000000,
                    "yoy_pct": -7.7,
                    "by_region": {"东南亚": {"current_usd": 45000000, "previous_usd": 38000000, "yoy_pct": 18.4}},
                    "top_partners": [{"code": "704", "name": "越南", "current_usd": 20000000, "previous_usd": 15000000, "yoy_pct": 33.3}]
                }
            }
        }
        dashboard = format_customs_dashboard(mock)
        tables = format_customs_for_journal(mock)
        print(json.dumps(dashboard, ensure_ascii=False, indent=2)[:1500])

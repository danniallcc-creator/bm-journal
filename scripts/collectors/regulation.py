"""监管与合规环境采集器
覆盖: EU Official Journal(建材法规) + 碳价格(EU ETS/CCER) + 绿色建筑认证 + CPSC召回
数据源:
  - EU Official Journal RSS (eur-lex.europa.eu)
  - EU ETS碳价 (EC CSV)
  - US CPSC召回 (cpsc.gov RSS)
  - 绿色建筑认证动态 (各认证机构)
"""
import json, re, time
from datetime import datetime, timedelta
from xml.etree import ElementTree
from ..utils import cache_get, cache_set, save_raw, log


# ===================== EU Official Journal (建材法规) =====================

# EUR-Lex RSS: 建筑产品相关法规
EU_OJ_RSS = "https://eur-lex.europa.eu/OJUDirective?locale=en&dateRange=true&startDate=&endDate=&year=&type=LEG&seriesCode=L"

# 建材相关关键词 (宽泛匹配提高召回率)
REGULATION_KEYWORDS = [
    "construction product", "building material", "cement", "steel",
    "timber", "glass", "ceramic", "insulation", "fire safety",
    "energy performance", "building regulation", "CPR",
    "REACH", "CBAM", "carbon border", "environmental product declaration",
    "green building", "sustainable construction", "waste framework",
    "circular economy", "recycl", "emission standard",
    # 扩展: 宽泛行业术语
    "construction sector", "building sector", "renovation",
    "infrastructure", "CE marking", "harmonised standard", "EN standard",
    "concrete", "brick", "tile", "plaster", "mortar", "aggregate",
    "thermal insulation", "ventilation", "roofing",
    "construction waste", "demolition", "prefabricat",
    "energy efficien", "zero emission building", "nearly zero",
    "EPBD", "construction regulation", "building code",
    "tariff", "anti-dumping", "safeguard measure", "import duty",
    "product safety", "recall", "non-compliance",
]


def _parse_rss_items(xml_text: str) -> list[dict]:
    """解析RSS/Atom XML, 提取items"""
    items = []
    try:
        root = ElementTree.fromstring(xml_text)
        # RSS 2.0
        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            desc = item.findtext("description", "").strip()
            pub_date = item.findtext("pubDate", "").strip()
            items.append({
                "title": title,
                "link": link,
                "description": desc[:500],
                "pub_date": pub_date
            })
        # Atom
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//atom:entry", ns):
            title = entry.findtext("atom:title", "", ns).strip()
            link_el = entry.find("atom:link", ns)
            link = link_el.get("href", "") if link_el is not None else ""
            summary = entry.findtext("atom:summary", "", ns).strip()
            pub_date = entry.findtext("atom:published", "", ns).strip()
            items.append({
                "title": title,
                "link": link,
                "description": summary[:500],
                "pub_date": pub_date
            })
    except ElementTree.ParseError as e:
        log.warning(f"RSS parse error: {e}")
    return items


def _filter_relevant(items: list[dict]) -> list[dict]:
    """过滤建材相关条目"""
    relevant = []
    for item in items:
        text = f"{item['title']} {item['description']}".lower()
        matched_keywords = [kw for kw in REGULATION_KEYWORDS if kw.lower() in text]
        if matched_keywords:
            item["matched_keywords"] = matched_keywords
            item["relevance_score"] = len(matched_keywords)
            relevant.append(item)
    relevant.sort(key=lambda x: -x.get("relevance_score", 0))
    return relevant


def collect_eu_regulations() -> dict:
    """采集EU Official Journal中与建材相关的法规

    Returns:
        {
            "items": [{"title": "...", "link": "...", "summary": "...", "tag": "esg"|"standard"|"warn"}, ...],
            "total_scanned": 50,
            "relevant_count": 3,
            "status": "ok"
        }
    """
    log.info("=== Collecting EU regulations ===")

    cache_key = "eu_regulations"
    cached = cache_get(cache_key, "regulation", ttl=3600 * 24 * 3)
    if cached:
        return cached

    import requests
    result = {"items": [], "total_scanned": 0, "relevant_count": 0, "status": "ok"}

    # 尝试多个EUR-Lex / EU RSS端点
    rss_urls = [
        # EUR-Lex CELLAR RSS - recent legislation (L series)
        "https://eur-lex.europa.eu/collection/oj/new-daily.feed?format=rss&locale=en",
        # EUR-Lex search RSS for construction-related topics
        "https://eur-lex.europa.eu/search.html?type=named&name=browse-by:legislation-in-force&CC_1_CODED=CODED14&qid=&DD_YEAR=&FM_CODED=REG&displayProfile=allRelAllCons498Doc&language=en&format=rss",
        # EU Commission GROW DG (Internal Market, Industry) - covers CPR
        "https://ec.europa.eu/growth/content/news_en/rss",
        # EU Commission press corner
        "https://ec.europa.eu/commission/presscorner/home/en/rss",
        # EU Single Market Economy news (covers construction products regulation)
        "https://single-market-economy.ec.europa.eu/news_en/rss",
        # RAPEX/Safety Gate - product recalls including building materials
        "https://ec.europa.eu/safety-gate-alerts/screen/webReport/alertDetail/rss",
    ]

    all_items = []
    for url in rss_urls:
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if resp.status_code == 200:
                items = _parse_rss_items(resp.text)
                all_items.extend(items)
                log.info(f"  EU RSS ({url.split('/')[-2]}): {len(items)} items")
            else:
                log.warning(f"  EU RSS failed ({resp.status_code}): {url.split('/')[-2]}")
        except Exception as e:
            log.warning(f"  EU RSS error: {e}")
        time.sleep(0.5)

    result["total_scanned"] = len(all_items)
    relevant = _filter_relevant(all_items)
    result["relevant_count"] = len(relevant)

    for item in relevant[:10]:
        # 自动分类
        text = f"{item['title']} {item['description']}".lower()
        tag = "standard"
        if any(w in text for w in ["carbon", "emission", "esg", "sustainable", "circular", "recycl"]):
            tag = "esg"
        elif any(w in text for w in ["warning", "recall", "non-compliance", "sanction", "ban"]):
            tag = "warn"

        result["items"].append({
            "title": item["title"],
            "link": item["link"],
            "summary": item["description"][:200],
            "tag": tag,
            "source": "EU Official Journal",
            "pub_date": item.get("pub_date", "")
        })

    cache_set(cache_key, "regulation", result)
    save_raw("regulation", "eu_regulations", result)
    log.info(f"EU regulations: {result['relevant_count']}/{result['total_scanned']} relevant")
    return result


# ===================== 碳价格 (EU ETS / CCER) =====================

def collect_carbon_prices() -> dict:
    """碳价格数据采集
    EU ETS: 从EU碳市场获取
    CCER: 中国全国碳市场(上海环交所)
    """
    log.info("=== Collecting carbon prices ===")

    cache_key = "carbon_prices"
    cached = cache_get(cache_key, "regulation", ttl=3600 * 24 * 2)
    if cached:
        return cached

    import requests
    result = {"markets": {}, "status": "ok"}

    # EU ETS - 尝试从多个公开数据源获取
    ets_sources = [
        # ICAP ETS数据库 (CSV)
        ("EU ETS", "https://icapcarbonaction.com/system/files/ets/eu-ets-historical-prices.csv"),
        # Ember Climate carbon price tracker (JSON API)
        ("EU ETS", "https://ember-climate.org/api/carbon-price/eu-ets/"),
    ]

    for name, url in ets_sources:
        if name in result["markets"]:
            break  # 已有数据,跳过
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if resp.status_code == 200 and len(resp.text) > 100:
                # 尝试JSON格式 (Ember等API)
                if resp.headers.get("content-type", "").startswith("application/json"):
                    try:
                        jdata = resp.json()
                        # Ember格式: {"price": X, "date": "YYYY-MM-DD", "currency": "EUR"}
                        if isinstance(jdata, dict) and "price" in jdata:
                            result["markets"][name] = {
                                "price": str(jdata["price"]),
                                "date": jdata.get("date", ""),
                                "unit": "EUR/tCO2",
                                "source": url.split("/")[2]
                            }
                            log.info(f"  {name}: {jdata['price']} EUR/tCO2 (JSON)")
                            continue
                    except (json.JSONDecodeError, ValueError):
                        pass
                # CSV格式 (ICAP)
                lines = resp.text.strip().split("\n")
                if len(lines) >= 2:
                    header = lines[0].split(",")
                    last_row = lines[-1].split(",")
                    # 找date和price列
                    date_col = next((i for i, h in enumerate(header) if "date" in h.lower()), 0)
                    price_col = next((i for i, h in enumerate(header) if "price" in h.lower() or "settl" in h.lower() or "allow" in h.lower()), -1)
                    if price_col >= 0 and len(last_row) > price_col:
                        result["markets"][name] = {
                            "price": last_row[price_col].strip(),
                            "date": last_row[date_col].strip() if date_col < len(last_row) else "",
                            "unit": "EUR/tCO2",
                            "source": url.split("/")[2]
                        }
                        log.info(f"  {name}: {result['markets'][name]['price']} EUR/tCO2 (CSV)")
        except Exception as e:
            log.warning(f"  {name} fetch error: {e}")

    # 中国碳市场 (CCER/CET)
    try:
        # 上海环境能源交易所
        resp = requests.get("https://www.cneeex.com/json/nbqkjy/list_01.html",
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if resp.status_code == 200:
            # 尝试解析返回的JSON
            try:
                data = resp.json()
                if isinstance(data, list) and data:
                    latest = data[0]
                    result["markets"]["China CET"] = {
                        "price": str(latest.get("price", latest.get("avg_price", "N/A"))),
                        "date": str(latest.get("trade_date", latest.get("date", ""))),
                        "unit": "CNY/tCO2",
                        "source": "cneeex.com"
                    }
                    log.info(f"  China CET: {result['markets']['China CET']['price']} CNY/tCO2")
            except (json.JSONDecodeError, ValueError):
                pass
    except Exception as e:
        log.warning(f"  China CET error: {e}")

    cache_set(cache_key, "regulation", result)
    save_raw("regulation", "carbon_prices", result)
    return result


# ===================== US CPSC 产品召回 =====================

def collect_cpsc_recalls() -> dict:
    """US Consumer Product Safety Commission 产品召回
    API: https://www.saferproducts.gov/RestWebServices/Recall
    """
    log.info("=== Collecting CPSC recalls ===")

    cache_key = "cpsc_recalls"
    cached = cache_get(cache_key, "regulation", ttl=3600 * 24 * 5)
    if cached:
        return cached

    import requests
    result = {"recalls": [], "total": 0, "relevant": 0, "status": "ok"}

    # CPSC API - 最近的召回
    try:
        resp = requests.get("https://www.saferproducts.gov/RestWebServices/Recall",
                            params={"format": "json"},
                            headers={"User-Agent": "Mozilla/5.0"},
                            timeout=15)
        if resp.status_code == 200:
            recalls = resp.json()
            if isinstance(recalls, list):
                result["total"] = len(recalls)
                # 过滤建材相关
                for recall in recalls[:50]:
                    desc = f"{recall.get('Title', '')} {recall.get('Description', '')}".lower()
                    if any(kw in desc for kw in ["window", "door", "floor", "tile", "light", "heater",
                                                  "furnace", "smoke", "carbon monoxide", "glass",
                                                  "ladder", "scaffold", "tool", "paint", "coating",
                                                  "dresser", "furniture", "shelf", "cabinet", "railing"]):
                        hazards = recall.get("Hazards", [])
                        hazard_text = hazards[0].get("HazardType", "") if hazards else ""
                        result["recalls"].append({
                            "title": recall.get("Title", ""),
                            "description": recall.get("Description", "")[:300],
                            "date": recall.get("RecallDate", ""),
                            "hazard": hazard_text,
                            "link": recall.get("URL", ""),
                            "source": "CPSC"
                        })
                result["relevant"] = len(result["recalls"])
                log.info(f"  CPSC: {result['relevant']}/{result['total']} recalls relevant")
    except Exception as e:
        log.warning(f"  CPSC error: {e}")
        result["status"] = "fetch_failed"

    cache_set(cache_key, "regulation", result)
    save_raw("regulation", "cpsc_recalls", result)
    return result


# ===================== 汇总 & 格式化 =====================

def collect_all_regulations() -> dict:
    """汇总所有监管数据"""
    eu = collect_eu_regulations()
    carbon = collect_carbon_prices()
    cpsc = collect_cpsc_recalls()

    return {
        "eu_regulations": eu,
        "carbon_prices": carbon,
        "cpsc_recalls": cpsc,
        "collected_at": datetime.now().isoformat()
    }


def format_regulation_items(reg_data: dict) -> list[dict]:
    """转化为期刊regulation板块格式"""
    items = []

    # EU法规
    for item in reg_data.get("eu_regulations", {}).get("items", [])[:5]:
        items.append({
            "title": item["title"][:80],
            "summary": item["summary"],
            "tag": item.get("tag", "standard"),
            "source": item.get("source", "EU"),
            "link": item.get("link", ""),
            "date": item.get("pub_date", "")
        })

    # 碳价格变动
    for market, info in reg_data.get("carbon_prices", {}).get("markets", {}).items():
        items.append({
            "title": f"{market}碳价: {info.get('price', 'N/A')} {info.get('unit', '')}",
            "summary": f"数据来源: {info.get('source', 'N/A')}, 日期: {info.get('date', 'N/A')}",
            "tag": "esg",
            "source": market,
            "link": "",
            "date": info.get("date", "")
        })

    # CPSC召回
    for recall in reg_data.get("cpsc_recalls", {}).get("recalls", [])[:3]:
        items.append({
            "title": recall["title"][:80],
            "summary": recall.get("description", "")[:200],
            "tag": "warn",
            "source": "US CPSC",
            "link": recall.get("link", ""),
            "date": recall.get("date", "")
        })

    return items[:10]


if __name__ == "__main__":
    data = collect_all_regulations()
    items = format_regulation_items(data)
    print(f"\nRegulation items: {len(items)}")
    for item in items[:5]:
        print(f"  [{item['tag']}] {item['title'][:60]}")

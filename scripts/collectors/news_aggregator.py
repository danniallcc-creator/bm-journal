"""新闻聚合器 - 建材/房地产/大宗商品行业新闻
覆盖: 全球权威媒体RSS + 行业专业媒体 + 关键词过滤 + 自动分类
数据源:
  - 国际主流: Reuters, Bloomberg(公开), FT(摘要), CNN Business
  - 行业专业: Construction Dive, Global Construction Review, PV Magazine
  - 大宗商品: Metal Bulletin(摘要), Mining.com
  - 房地产: HousingWire, Realtor.com Research
"""
import json, re, time
from datetime import datetime, timedelta
from xml.etree import ElementTree
from ..utils import cache_get, cache_set, save_raw, log

# ===================== RSS源配置 =====================

RSS_FEEDS = {
    # 国际主流
    "Reuters-Business": "https://www.reutersagency.com/feed/?taxonomy=best-topics&post_type=best",
    "Reuters-Markets": "https://www.reutersagency.com/feed/?taxonomy=best-sectors&post_type=best",

    # 建筑/房地产
    "Construction Dive": "https://www.constructiondive.com/feeds/news/",
    "Global Construction Review": "https://www.globalconstructionreview.com/feed/",
    "Construction Enquirer": "https://www.constructionenquirer.com/feed/",
    "HousingWire": "https://www.housingwire.com/feed/",
    "Builder Online": "https://www.builderonline.com/rss",

    # 大宗商品/贸易
    "Mining.com": "https://www.mining.com/feed/",
    "SteelOrbis": "https://www.steelorbis.com/rss/news.xml",
    "Argus Media": "https://www.argusmedia.com/en/rss",

    # 可持续/绿色建材
    "PV Magazine": "https://www.pv-magazine.com/feed/",
    "Green Building Council": "https://www.usgbc.org/rss",

    # 创新/技术
    "3DPrint.com": "https://3dprint.com/feed/",
    "ArchDaily": "https://www.archdaily.com/feed",

    # 中文财经
    "Sina Finance": "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&num=20&page=1",
}

# 建材/房地产/大宗商品关键词 (过滤用)
NEWS_KEYWORDS = {
    "macro": [
        "interest rate", "central bank", "federal reserve", "inflation", "gdp",
        "construction pmi", "manufacturing pmi", "housing market", "mortgage rate",
        "infrastructure", "stimulus", "recession", "monetary policy", "fiscal",
        "央行", "利率", "通胀", "基建", "房地产", "货币政策"
    ],
    "supply_chain": [
        "shipping", "freight", "supply chain", "container", "port congestion",
        "tariff", "trade war", "anti-dumping", "sanction", "embargo",
        "steel price", "cement price", "lumber price", "copper price",
        "运费", "关税", "供应链", "钢材价格", "水泥价格"
    ],
    "real_estate": [
        "housing", "home sales", "home price", "new construction", "building permit",
        "commercial real estate", "apartment", "renovation", "remodeling",
        "foreclosure", "housing starts", "single family", "multifamily",
        "房价", "新房", "二手房", "装修", "翻新"
    ],
    "commodity": [
        "iron ore", "aluminum", "copper", "zinc", "nickel", "steel",
        "cement", "timber", "lumber", "sand", "gravel", "aggregate",
        "natural gas", "coal", "crude oil", "petroleum",
        "铁矿石", "铝", "铜", "钢材", "木材", "水泥"
    ],
    "regulation": [
        "carbon", "emission", "green building", "leed", "breeam", "energy code",
        "fire safety", "building code", "environmental", "sustainable",
        "cbam", "reach", "recycl", "circular economy", "esg",
        "碳排放", "绿色建筑", "环保", "节能", "碳关税"
    ],
    "innovation": [
        "3d print", "modular", "prefab", "smart glass", "self-healing",
        "aerogel", "bipv", "mass timber", "cross laminated", "geopolymer",
        "low carbon cement", "green cement", "recycled",
        "3d打印", "装配式", "模块化", "智能玻璃"
    ],
    "trade": [
        "export", "import", "trade flow", "trade balance", "customs",
        "rcep", "aftcfta", "free trade", "trade agreement",
        "出口", "进口", "贸易", "海关"
    ]
}


# ===================== RSS采集核心 =====================

def _fetch_rss(url: str, source_name: str, timeout: int = 12) -> list[dict]:
    """获取并解析单个RSS源"""
    import requests

    # Sina等API格式特殊处理
    if "sina.com.cn" in url:
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("result", {}).get("data", [])
                return [{
                    "title": item.get("title", ""),
                    "link": item.get("url", ""),
                    "description": item.get("summary", item.get("intro", ""))[:300],
                    "pub_date": item.get("ctime", ""),
                    "source": source_name
                } for item in items[:15]]
        except Exception:
            return []

    # 标准RSS/Atom解析
    try:
        resp = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept": "application/rss+xml, application/xml, text/xml, */*"
        }, timeout=timeout)
        if resp.status_code != 200:
            return []

        items = []
        try:
            root = ElementTree.fromstring(resp.text)
        except ElementTree.ParseError:
            # 尝试清理HTML实体
            cleaned = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)', '&amp;', resp.text)
            root = ElementTree.fromstring(cleaned)

        # RSS 2.0
        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            desc = item.findtext("description", "").strip()
            pub = item.findtext("pubDate", "").strip()
            items.append({
                "title": title, "link": link,
                "description": desc[:400], "pub_date": pub,
                "source": source_name
            })

        # Atom
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//atom:entry", ns):
            title = entry.findtext("atom:title", "", ns).strip()
            link_el = entry.find("atom:link", ns)
            link = link_el.get("href", "") if link_el is not None else ""
            summary = entry.findtext("atom:summary", entry.findtext("atom:content", "", ns), ns).strip()
            pub = entry.findtext("atom:published", entry.findtext("atom:updated", "", ns), ns).strip()
            items.append({
                "title": title, "link": link,
                "description": summary[:400], "pub_date": pub,
                "source": source_name
            })

        return items
    except Exception as e:
        log.debug(f"RSS parse error ({source_name}): {e}")
        return []


def _classify_article(item: dict) -> list[str]:
    """根据关键词分类新闻"""
    text = f"{item.get('title', '')} {item.get('description', '')}".lower()
    matched_categories = []
    for category, keywords in NEWS_KEYWORDS.items():
        if any(kw.lower() in text for kw in keywords):
            matched_categories.append(category)
    return matched_categories


def _is_relevant(item: dict) -> bool:
    """判断文章是否与建材行业相关"""
    categories = _classify_article(item)
    return len(categories) > 0


# ===================== 主采集函数 =====================

def collect_all_news() -> dict:
    """从所有RSS源采集新闻, 过滤+分类

    Returns:
        {
            "articles": [{"title", "link", "summary", "categories", "source", "pub_date"}],
            "sources_ok": 5,
            "sources_failed": 3,
            "total_scanned": 200,
            "relevant_count": 30,
            "by_category": {"macro": 10, "supply_chain": 5, ...},
            "status": "ok"
        }
    """
    log.info("=== Collecting news from RSS feeds ===")

    cache_key = "all_news"
    cached = cache_get(cache_key, "news", ttl=3600 * 6)  # 6小时缓存
    if cached:
        return cached

    all_articles = []
    sources_ok = 0
    sources_failed = 0

    for source_name, url in RSS_FEEDS.items():
        items = _fetch_rss(url, source_name)
        if items:
            sources_ok += 1
            log.info(f"  {source_name}: {len(items)} articles")
            for item in items:
                item["categories"] = _classify_article(item)
                all_articles.append(item)
        else:
            sources_failed += 1
            log.debug(f"  {source_name}: no data")
        time.sleep(0.3)

    # 过滤: 只保留相关文章
    relevant = [a for a in all_articles if a["categories"]]

    # 按相关度排序 (匹配的分类越多越靠前)
    relevant.sort(key=lambda a: -len(a["categories"]))

    # 按分类统计
    by_category = {}
    for article in relevant:
        for cat in article["categories"]:
            by_category[cat] = by_category.get(cat, 0) + 1

    # 去重 (标题相似度)
    seen_titles = set()
    unique_articles = []
    for article in relevant:
        title_key = re.sub(r'\W+', '', article["title"].lower())[:50]
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique_articles.append(article)

    # 构建输出
    output_articles = []
    for article in unique_articles[:50]:
        output_articles.append({
            "title": article["title"][:100],
            "link": article.get("link", ""),
            "summary": article.get("description", "")[:200],
            "categories": article["categories"],
            "source": article.get("source", ""),
            "pub_date": article.get("pub_date", "")
        })

    output = {
        "articles": output_articles,
        "sources_ok": sources_ok,
        "sources_failed": sources_failed,
        "total_scanned": len(all_articles),
        "relevant_count": len(unique_articles),
        "by_category": by_category,
        "collected_at": datetime.now().isoformat(),
        "status": "ok" if output_articles else "no_data"
    }

    cache_set(cache_key, "news", output)
    save_raw("news", "all_articles", output)

    log.info(f"News: {len(unique_articles)} relevant / {len(all_articles)} total "
             f"({sources_ok} sources ok, {sources_failed} failed)")
    log.info(f"  Categories: {by_category}")
    return output


def format_news_articles(news_data: dict) -> dict:
    """将新闻数据转化为期刊各板块的文章格式

    Returns:
        {
            "macro": [{"tag", "title", "summary", "source", "link"}],
            "regional": [...],
            "supply_chain": [...],
            "regulation": [...],
            "innovation": [...]
        }
    """
    sections = {
        "macro": [],
        "supply_chain": [],
        "regulation": [],
        "innovation": [],
        "real_estate": []
    }

    tag_map = {
        "macro": "宏观",
        "supply_chain": "供应链",
        "regulation": "监管",
        "innovation": "创新",
        "real_estate": "房地产",
        "commodity": "大宗",
        "trade": "贸易"
    }

    for article in news_data.get("articles", []):
        cats = article.get("categories", [])
        if not cats:
            continue

        primary_cat = cats[0]  # 主分类
        tags = [tag_map.get(c, c) for c in cats]

        formatted = {
            "tag": " / ".join(tags[:3]),
            "title": article["title"],
            "summary": article.get("summary", ""),
            "source": article.get("source", ""),
            "link": article.get("link", "")
        }

        if primary_cat in sections:
            sections[primary_cat].append(formatted)
        elif primary_cat in ["commodity", "trade"]:
            sections["supply_chain"].append(formatted)
        elif primary_cat == "real_estate":
            sections["real_estate"].append(formatted)

    # 每个板块最多5条
    for section in sections:
        sections[section] = sections[section][:5]

    return sections


if __name__ == "__main__":
    data = collect_all_news()
    sections = format_news_articles(data)
    for section, articles in sections.items():
        if articles:
            print(f"\n--- {section} ({len(articles)}) ---")
            for a in articles[:3]:
                print(f"  [{a['tag']}] {a['title'][:60]} ({a['source']})")

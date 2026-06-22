"""基建宏观情报采集器 - 全球基建/重建/翻新需求分析
覆盖:
  - 国际开发机构: World Bank, UN, ADB, EBRD, IDB, AfDB
  - 区域基建新闻: EU基建基金, 美国IRA/IIJA, 一带一路, 战后重建
  - 建材上市公司市场情报: 区域龙头财报/订单/扩产
  - 宏观需求研判: 各国建筑PMI、基建投资增速、招标量
数据源:
  - RSS: World Bank blogs, UN News, ADB, EBRD, IDB
  - 行业: GlobalData Construction, KHL Group, ENR
  - 研究: Crossref/RePEc (基建投资论文摘要)
"""
import json, re, time
from datetime import datetime, timedelta
from xml.etree import ElementTree
from ..utils import cache_get, cache_set, save_raw, log


# ===================== 区域定义 =====================

REGIONS = {
    "EU 欧盟": {
        "keywords": [
            "european union", "eu commission", "ecb", "european", "eurozone",
            "recovery fund", "next generation eu", "green deal", "renovation wave",
            "european investment bank", "structural fund", "cohesion fund",
        ],
        "focus": "绿色建筑翻新、能效改造、REPowerEU能源独立基建",
        "tag": "欧盟翻新",
    },
    "北美 North America": {
        "keywords": [
            "united states", "canada", "mexico", "infrastructure bill", "iija",
            "inflation reduction act", "bipartisan infrastructure", "dot",
            "american society of civil engineers", "highway trust fund",
        ],
        "focus": "IIJA万亿基建、IRA清洁能源、桥梁公路翻新",
        "tag": "北美基建",
    },
    "中东 Middle East": {
        "keywords": [
            "saudi arabia", "vision 2030", "neom", "red sea", "qiddiya",
            "uae", "dubai", "expo", "qatar", "bahrain", "oman",
            "gulf", "gcc", "middle east construction",
        ],
        "focus": "沙特NEOM等超级工程、海湾国家城市新建、旅游地产",
        "tag": "中东基建",
    },
    "非洲 Africa": {
        "keywords": [
            "africa", "afdb", "african development bank", "afreximbank",
            "lagos", "nairobi", "cairo", "addis ababa", "kinshasa",
            "african union", "afcf ta", "program for infrastructure",
        ],
        "focus": "AfDB基建融资、城市化住房、跨境交通走廊",
        "tag": "非洲基建",
    },
    "亚非拉重建 Post-conflict": {
        "keywords": [
            "ukraine", "reconstruction", "rebuild", "post-conflict",
            "world bank reconstruction", "marshall plan", "donor conference",
            "syria reconstruction", "afghanistan rebuild", "iraq reconstruction",
        ],
        "focus": "乌克兰战后重建、中东重建、国际援助基建",
        "tag": "战后重建",
    },
    "东南亚 Southeast Asia": {
        "keywords": [
            "asean", "vietnam", "indonesia", "thailand", "philippines",
            "malaysia", "singapore", "myanmar", "cambodia", "laos",
            "adb", "asian development bank", "belt and road",
        ],
        "focus": "ADB融资、城市化加速、产业转移基建需求",
        "tag": "东南亚基建",
    },
    "南亚 South Asia": {
        "keywords": [
            "india", "pakistan", "bangladesh", "sri lanka", "nepal",
            "modi infrastructure", "pm gati shakti", "smart cities mission",
            "national infrastructure pipeline", "housing for all",
        ],
        "focus": "印度Gati Shakti国家基建计划、保障房、高铁",
        "tag": "南亚基建",
    },
    "中亚与俄罗斯 CIS/Russia": {
        "keywords": [
            "russia", "kazakhstan", "uzbekistan", "turkmenistan",
            "cis", "eurasian", "silk road economic belt",
            "central asia", "trans-caspian",
        ],
        "focus": "中亚走廊、欧亚经济联盟基建、一带一路中亚段",
        "tag": "中亚基建",
    },
    "拉美 Latin America": {
        "keywords": [
            "brazil", "mexico", "colombia", "chile", "argentina", "peru",
            "inter-american development bank", "idb", "caf",
            "latin america infrastructure", "nearshoring",
        ],
        "focus": "IDB融资、近岸外包基建、矿业/能源项目",
        "tag": "拉美基建",
    },
}


# ===================== RSS源 =====================

INFRA_RSS_FEEDS = {
    # World Bank
    "World Bank-Blogs": "https://blogs.worldbank.org/rss/all",
    "World Bank-Projects": "https://www.worldbank.org/en/news/rss",

    # UN
    "UN News-Economic": "https://news.un.org/feed/subscribe/en/news/topic/economic-development/feed/rss.xml",
    "UN News-Sustainable": "https://news.un.org/feed/subscribe/en/news/topic/sustainable-development/feed/rss.xml",

    # 区域开发银行
    "ADB-News": "https://www.adb.org/news/rss.xml",
    "EBRD-News": "https://www.ebrd.com/news/rss",
    "AfDB-News": "https://www.afdb.org/en/rss.xml",

    # 建筑行业专业媒体
    "GlobalData-Construction": "https://www.globaldata.com/store/report-category/construction/feed/",
    "KHL-Group": "https://www.khl.com/feed",
    "Construction-Record": "https://www.constructionrecord.com/feed/",

    # 国际工程
    "ENR-International": "https://www.enr.com/rss/266-international",
}


# ===================== 建材上市公司关键词 (区域龙头) =====================

REGIONAL_COMPANIES = {
    "EU": ["Holcim", "HeidelbergCement", "Saint-Gobain", "Kingspan", "CRH", "Lafarge"],
    "北美": ["USG", "Vulcan Materials", "Martin Marietta", "Caterpillar", "Deere"],
    "中东": ["Saudi Cement", "Yamama Cement", "Al Rajhi", "Emaar"],
    "东南亚": ["Siam Cement", "Semen Indonesia", "Petronas", "Astro"],
    "南亚": ["UltraTech", "ACC", "Ambuja", "JSW Cement", "Larsen & Toubro"],
    "拉美": ["Votorantim", "Cementos Progreso", "Cementos Pacasmayo"],
    "非洲": ["Dangote Cement", "PPC", "Lafarge Africa", "Bamburi"],
    "中国出口相关": ["海螺水泥", "华新水泥", "三一重工", "徐工机械", "中国交建"],
}


# ===================== 核心采集函数 =====================

def _fetch_rss(url: str, source: str, timeout: int = 12) -> list[dict]:
    """获取并解析RSS"""
    import requests

    items = []
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        if resp.status_code != 200:
            return items

        root = ElementTree.fromstring(resp.text)
        # RSS 2.0
        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            desc = item.findtext("description", "").strip()
            pub_date = item.findtext("pubDate", "").strip()
            if title:
                items.append({
                    "title": title[:200],
                    "link": link,
                    "description": desc[:500],
                    "source": source,
                    "pub_date": pub_date,
                })
        # Atom
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//atom:entry", ns):
            title = entry.findtext("atom:title", "", ns).strip()
            link_el = entry.find("atom:link", ns)
            link = link_el.get("href", "") if link_el is not None else ""
            desc = entry.findtext("atom:summary", "", ns).strip()
            pub_date = entry.findtext("atom:published", "", ns).strip()
            if title:
                items.append({
                    "title": title[:200],
                    "link": link,
                    "description": desc[:500],
                    "source": source,
                    "pub_date": pub_date,
                })
    except Exception as e:
        log.warning(f"Infra RSS {source} error: {e}")

    return items


def _classify_item(item: dict) -> str | None:
    """将一条信息分类到对应区域"""
    text = f"{item['title']} {item['description']}".lower()
    for region, info in REGIONS.items():
        for kw in info["keywords"]:
            if kw in text:
                return region
    return None


def _score_relevance(item: dict) -> int:
    """评估与建材/基建的相关性 (0-10)"""
    text = f"{item['title']} {item['description']}".lower()
    score = 0

    # 核心建材词 +3
    construction_kws = ["cement", "concrete", "steel", "timber", "lumber", "brick",
                        "tile", "glass", "insulation", "roofing", "aggregate",
                        "building material", "construction", "building", "infrastructure"]
    for kw in construction_kws:
        if kw in text:
            score += 3
            break

    # 项目/投资词 +2
    project_kws = ["project", "contract", "tender", "bidding", "award", "fund",
                   "loan", "investment", "billion", "million", "budget", "spend"]
    for kw in project_kws:
        if kw in text:
            score += 2
            break

    # 增长/需求词 +2
    growth_kws = ["growth", "demand", "expansion", "boost", "increase", "surge",
                  "stimulus", "recovery", "reconstruction", "rebuild", "renovation"]
    for kw in growth_kws:
        if kw in text:
            score += 2
            break

    # 区域词 +1
    for region, info in REGIONS.items():
        for kw in info["keywords"]:
            if kw in text:
                score += 1
                break

    return min(score, 10)


def _estimate_impact(item: dict) -> int:
    """估算对建材行业的冲击 (0-5)"""
    text = f"{item['title']} {item['description']}".lower()

    # 大额投资/重建 +5
    big_money = ["billion", "reconstruction fund", "marshall plan", "major infrastructure"]
    for kw in big_money:
        if kw in text:
            return 5

    # 政策/融资 +4
    policy = ["government", "ministry", "central bank", "loan approved",
              "funding", "stimulus package", "budget allocation"]
    for kw in policy:
        if kw in text:
            return 4

    # 项目/合同 +3
    project = ["contract", "award", "groundbreaking", "project launched"]
    for kw in project:
        if kw in text:
            return 3

    # 一般新闻 +1
    return 1


def collect_all_infra_intelligence() -> dict:
    """采集全球基建宏观情报

    Returns:
        {
            "articles": [{"region", "title", "summary", "source", "link", "tag", "impact", "date"}],
            "regional_coverage": {"EU": [items], "北美": [items], ...},
            "company_mentions": {"EU": ["Holcim", ...], ...},
            "total_scanned": 200,
            "relevant_count": 30,
            "status": "ok"
        }
    """
    log.info("=== Collecting infrastructure intelligence ===")

    cache_key = "infra_intelligence"
    cached = cache_get(cache_key, "infra", ttl=3600 * 24 * 3)
    if cached:
        log.info(f"Infra intelligence: using cache ({cached.get('relevant_count', 0)} relevant)")
        return cached

    import requests

    # 采集RSS
    all_items = []
    feeds_ok = 0
    for source, url in INFRA_RSS_FEEDS.items():
        items = _fetch_rss(url, source)
        if items:
            feeds_ok += 1
        all_items.extend(items)
        log.info(f"  Infra RSS {source}: {len(items)} items")
        time.sleep(0.3)

    log.info(f"Infra RSS: {len(all_items)} total from {feeds_ok}/{len(INFRA_RSS_FEEDS)} feeds")

    # 分类+评分
    regional_items = {r: [] for r in REGIONS}
    company_mentions = {r: [] for r in REGIONAL_COMPANIES}
    articles = []

    for item in all_items:
        region = _classify_item(item)
        if not region:
            continue

        score = _score_relevance(item)
        if score < 2:  # 低相关性过滤
            continue

        impact = _estimate_impact(item)
        tag = REGIONS[region].get("tag", "基建")

        # 检测公司提及
        text = f"{item['title']} {item['description']}".lower()
        for comp_region, companies in REGIONAL_COMPANIES.items():
            for comp in companies:
                if comp.lower() in text:
                    if comp not in company_mentions.get(comp_region, []):
                        company_mentions.setdefault(comp_region, []).append(comp)

        article = {
            "region": region,
            "title": item["title"],
            "summary": item["description"][:300],
            "source": item["source"],
            "link": item["link"],
            "tag": tag,
            "impact": impact,
            "date": item.get("pub_date", ""),
            "relevance_score": score,
        }

        regional_items.setdefault(region, []).append(article)
        articles.append(article)

    # 按区域+相关性排序,每个区域取top 3
    for region in regional_items:
        regional_items[region].sort(key=lambda x: -x["relevance_score"])
        regional_items[region] = regional_items[region][:3]

    # 最终文章: 每区域取最好的2条,总共不超过15条
    top_articles = []
    for region in regional_items:
        top_articles.extend(regional_items[region][:2])
    top_articles.sort(key=lambda x: (-x["impact"], -x["relevance_score"]))
    top_articles = top_articles[:15]

    result = {
        "articles": top_articles,
        "regional_coverage": {
            r: {"items": regional_items[r][:5], "focus": REGIONS[r]["focus"]}
            for r in REGIONS
            if regional_items[r]
        },
        "company_mentions": {r: comps for r, comps in company_mentions.items() if comps},
        "total_scanned": len(all_items),
        "relevant_count": len(articles),
        "feeds_ok": feeds_ok,
        "feeds_total": len(INFRA_RSS_FEEDS),
        "collected_at": datetime.now().isoformat(),
        "status": "ok",
    }

    cache_set(cache_key, "infra", result)
    save_raw("infra", "intelligence", result)
    log.info(f"Infra intelligence: {result['relevant_count']}/{result['total_scanned']} relevant, "
             f"{feeds_ok}/{len(INFRA_RSS_FEEDS)} feeds ok, "
             f"{len(result['company_mentions'])} regions with company mentions")

    return result


def format_infra_articles(infra_data: dict) -> list[dict]:
    """将基建情报格式化为macro板块兼容的文章列表

    输出格式与central_bank.py和news_aggregator.py一致:
    {tag, title, summary, source, link, impact, date}
    """
    articles = infra_data.get("articles", [])
    if not articles:
        return []

    result = []
    for art in articles:
        # 构建综合摘要: 区域焦点 + 新闻摘要 + 公司提及
        region = art.get("region", "")
        focus = REGIONS.get(region, {}).get("focus", "")

        summary_parts = []
        if focus:
            summary_parts.append(f"[{focus}]")
        summary_parts.append(art.get("summary", ""))

        # 追加区域公司提及
        for comp_region, companies in infra_data.get("company_mentions", {}).items():
            if companies and len(companies) <= 3:
                summary_parts.append(f"(关注: {', '.join(companies)})")

        summary = " ".join(summary_parts)[:400]

        result.append({
            "tag": art.get("tag", "基建"),
            "title": art.get("title", ""),
            "summary": summary,
            "source": art.get("source", ""),
            "link": art.get("link", ""),
            "impact": art.get("impact", 0),
            "date": art.get("date", ""),
        })

    return result


def format_regional_infra_summary(infra_data: dict) -> str:
    """生成区域基建宏观研判摘要文本(用于keyTakeaways)

    Returns: 200-400字的综合研判
    """
    coverage = infra_data.get("regional_coverage", {})
    if not coverage:
        return ""

    parts = ["全球基建宏观研判:"]

    # 按影响度排序区域
    region_scores = []
    for region, data in coverage.items():
        items = data.get("items", [])
        if not items:
            continue
        avg_impact = sum(it.get("impact", 0) for it in items) / len(items)
        region_scores.append((region, data.get("focus", ""), items[0], avg_impact))

    region_scores.sort(key=lambda x: -x[3])

    for region, focus, top_item, impact in region_scores[:5]:
        parts.append(f"• {region}: {top_item.get('title', '')[:80]}")

    # 追加公司情报
    mentions = infra_data.get("company_mentions", {})
    if mentions:
        all_comps = []
        for comps in mentions.values():
            all_comps.extend(comps[:3])
        if all_comps:
            parts.append(f"关注企业动态: {', '.join(all_comps[:6])}")

    return "\n".join(parts)[:500]

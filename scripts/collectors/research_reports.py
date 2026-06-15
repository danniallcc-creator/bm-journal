"""投研报告摘要采集器
覆盖: 投研机构/智库/咨询机构的公开研究报告和观点
数据源:
  - Crossref (投行/券商研究报告, 免费)
  - World Bank Publications (发展报告)
  - IMF Working Papers
  - BIS (国际清算银行)
  - 各国央行研究报告
"""
import json, time
from datetime import datetime
from ..utils import fetch_json, cache_get, cache_set, save_raw, log

# ===================== 研报搜索配置 =====================

# 搜索主题: 建筑/房地产/大宗商品
RESEARCH_THEMES = {
    "global_construction": ["construction industry AND (outlook OR forecast OR market)"],
    "housing_market": ["housing market AND (real estate OR property OR mortgage)"],
    "infrastructure": ["infrastructure AND (investment OR spending OR development)"],
    "commodities": ["(steel OR cement OR timber OR copper) AND (demand OR price OR outlook)"],
    "green_finance": ["(green bond OR sustainable finance) AND (construction OR infrastructure)"],
    "trade": ["(building materials OR construction) AND (trade OR export OR import)"],
}

# 重点关注机构 (在Crossref中搜索publisher字段)
KEY_PUBLISHERS = [
    "World Bank", "IMF", "BIS", "OECD",
    "Asian Development Bank", "European Investment Bank",
]


def collect_crossref_reports(theme: str, queries: list[str]) -> dict:
    """从Crossref搜索研究报告"""
    all_reports = []

    for query in queries:
        params = {
            "query": query,
            "rows": 5,
            "sort": "relevance",
            "order": "desc",
            "filter": f"from-pub-date:{datetime.now().year - 1}-01-01",
            "select": "DOI,title,author,published,abstract,is-referenced-by-count,type,publisher,container-title"
        }

        data = fetch_json("https://api.crossref.org/works",
                          params=params, timeout=15, retries=1)
        if data:
            for item in data.get("message", {}).get("items", []):
                title = item.get("title", [""])[0] if item.get("title") else ""
                if not title or len(title) < 10:
                    continue

                # 标题+摘要相关性过滤
                abstract = (item.get("abstract", "") or "").lower()
                combined_text = (title + " " + abstract).lower()
                research_kw = ["construction", "building", "housing", "infrastructure",
                               "real estate", "property", "cement", "steel", "timber",
                               "commodity", "trade", "green", "sustainable", "mortgage",
                               "urban", "housing", "development", "economic"]
                if not any(kw in combined_text for kw in research_kw):
                    continue

                authors = item.get("author", [])
                author_str = "; ".join(a.get("family", "") for a in authors[:3])
                pub_date = item.get("published", {}).get("date-parts", [[]])[0]
                year = pub_date[0] if pub_date else ""
                publisher = item.get("publisher", "")
                journal = item.get("container-title", [""])[0] if item.get("container-title") else ""
                doc_type = item.get("type", "")

                all_reports.append({
                    "title": title,
                    "authors": author_str,
                    "year": year,
                    "publisher": publisher,
                    "journal": journal,
                    "type": doc_type,
                    "citations": item.get("is-referenced-by-count", 0),
                    "doi": item.get("DOI", ""),
                    "abstract": (item.get("abstract", "") or "")[:400],
                    "theme": theme,
                    "source": "Crossref"
                })
        time.sleep(1)

    # 去重
    seen = set()
    unique = []
    for r in all_reports:
        key = r["doi"] or r["title"][:50]
        if key not in seen:
            seen.add(key)
            unique.append(r)

    return {
        "theme": theme,
        "reports": unique,
        "total": len(unique),
        "status": "ok" if unique else "no_data"
    }


def collect_imf_working_papers() -> dict:
    """IMF Working Papers (eLibrary API)"""
    log.info("  IMF working papers")

    import requests
    reports = []
    try:
        # IMF eLibrary search
        resp = requests.get("https://www.elibrary.imf.org/view/journals/imfwp/aop/issue-title.xml",
                            params={"query": "construction OR housing OR infrastructure",
                                    "pageSize": 10, "sort": "dateSort:desc"},
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if resp.status_code == 200 and "xml" in resp.headers.get("Content-Type", ""):
            from xml.etree import ElementTree
            root = ElementTree.fromstring(resp.text)
            for item in root.iter("item"):
                title = item.findtext("title", "").strip()
                if title:
                    reports.append({
                        "title": title,
                        "publisher": "IMF",
                        "source": "IMF Working Papers",
                        "type": "working-paper"
                    })
    except Exception as e:
        log.warning(f"  IMF error: {e}")

    return {"reports": reports, "total": len(reports), "status": "ok" if reports else "no_data"}


def collect_bis_papers() -> dict:
    """BIS (Bank for International Settlements) publications"""
    log.info("  BIS publications")

    data = fetch_json("https://www.bis.org/list/bispress/index.rss", timeout=15, retries=1)
    reports = []
    if data:
        # 简单RSS解析
        import re
        titles = re.findall(r'<title[^>]*>(.*?)</title>', str(data))
        for title in titles[:10]:
            title = title.strip()
            if title and len(title) > 10:
                reports.append({
                    "title": title,
                    "publisher": "BIS",
                    "source": "BIS",
                    "type": "press-release"
                })

    return {"reports": reports, "total": len(reports), "status": "ok" if reports else "no_data"}


# ===================== 汇总 & 格式化 =====================

def collect_all_research() -> dict:
    """汇总所有投研报告数据"""
    log.info("=== Collecting research reports ===")

    cache_key = "research_all"
    cached = cache_get(cache_key, "research", ttl=3600 * 24 * 7)
    if cached:
        return cached

    results = {}

    # Crossref: 各主题研报
    for theme, queries in RESEARCH_THEMES.items():
        log.info(f"  Crossref: {theme}")
        results[theme] = collect_crossref_reports(theme, queries)
        count = results[theme].get("total", 0)
        if count:
            log.info(f"    → {count} reports")

    # IMF / BIS (轻量尝试)
    results["imf"] = collect_imf_working_papers()
    results["bis"] = collect_bis_papers()

    # 汇总
    total_reports = sum(r.get("total", 0) for r in results.values())
    themes_with_reports = sum(1 for r in results.values() if r.get("total", 0) > 0)

    output = {
        "results": results,
        "total_reports": total_reports,
        "themes_with_reports": themes_with_reports,
        "collected_at": datetime.now().isoformat(),
        "status": "ok" if total_reports > 0 else "no_data"
    }

    cache_set(cache_key, "research", output)
    save_raw("research", "all", output)

    log.info(f"Research: {themes_with_reports}/{len(results)} themes, {total_reports} reports total")
    return output


def format_research_highlights(research_data: dict) -> list[dict]:
    """转化为期刊可用的研报摘要列表"""
    highlights = []

    for theme, data in research_data.get("results", {}).items():
        reports = data.get("reports", [])
        if not reports:
            continue

        # 按引用数排序, 取top 2
        sorted_reports = sorted(reports, key=lambda r: r.get("citations", 0), reverse=True)
        for report in sorted_reports[:2]:
            highlights.append({
                "title": report["title"][:80],
                "summary": report.get("abstract", "")[:200] if report.get("abstract") else
                           f"{report.get('publisher', '')} {report.get('type', '')} ({report.get('year', '')})",
                "publisher": report.get("publisher", ""),
                "year": report.get("year", ""),
                "theme": theme,
                "doi": report.get("doi", ""),
                "source": report.get("source", "Crossref"),
                "citations": report.get("citations", 0)
            })

    # 按引用数和来源多样性排序
    highlights.sort(key=lambda h: -h.get("citations", 0))
    return highlights[:10]


if __name__ == "__main__":
    data = collect_all_research()
    highlights = format_research_highlights(data)
    print(f"\nResearch highlights: {len(highlights)}")
    for h in highlights[:5]:
        print(f"  [{h['theme']}] {h['title'][:60]} ({h['publisher']}, cited:{h['citations']})")

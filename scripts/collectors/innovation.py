"""创新与替代材料采集器
覆盖: 学术论文趋势 + 行业创新动态 + 技术关键词追踪
数据源:
  - Crossref API (学术论文, 免费, 无需Key)
  - DOAJ (开放获取期刊, 免费)
  - arXiv API (预印本论文, 免费)
  - 行业新闻RSS (PV Magazine, 3DPrint.com等 - 复用news_aggregator数据)
"""
import json, time, re
from datetime import datetime, timedelta
from xml.etree import ElementTree
from ..utils import fetch_json, cache_get, cache_set, save_raw, log

# ===================== 创新技术关键词库 =====================

INNOVATION_TOPICS = {
    "低碳水泥": ["green cement", "low carbon cement", "geopolymer cement", "LC3 cement", "CCUS cement"],
    "自修复混凝土": ["self-healing concrete", "bacterial concrete", "autogenous healing"],
    "3D打印建筑": ["3D printed building", "3D concrete printing", "additive manufacturing construction"],
    "气凝胶保温": ["aerogel insulation", "silica aerogel", "aerogel building"],
    "光伏一体化(BIPV)": ["building integrated photovoltaic", "BIPV", "solar facade"],
    "大木结构(CLT)": ["cross laminated timber", "mass timber", "CLT building", "engineered wood"],
    "模块化建筑": ["modular construction", "prefabricated building", "volumetric construction"],
    "智能玻璃": ["smart glass", "electrochromic glass", "switchable glazing"],
    "再生钢材": ["recycled steel", "green steel", "hydrogen steel", "EAF steel"],
    "数字孪生": ["digital twin construction", "BIM digital twin", "construction 4.0"],
    "碳捕集建材": ["carbon capture building", "mineralization concrete", "CO2 cured concrete"],
}


def collect_crossref_papers(topic: str, keywords: list[str],
                             year_from: int = None) -> dict:
    """Crossref API - 学术论文搜索
    免费, 无需Key, 返回标题/作者/引用/摘要等
    """
    if year_from is None:
        year_from = datetime.now().year - 1

    # 使用通用query搜索, 按相关性排序获取最匹配的结果
    query = " ".join(keywords[:2])
    params = {
        "query": query,
        "rows": 10,
        "sort": "relevance",
        "order": "desc",
        "filter": f"from-pub-date:{year_from}-01-01",
        "select": "DOI,title,author,published,abstract,is-referenced-by-count,type"
    }

    data = fetch_json("https://api.crossref.org/works",
                      params=params, timeout=15, retries=1)
    if not data:
        return {"topic": topic, "papers": [], "total": 0, "status": "no_data"}

    items = data.get("message", {}).get("items", [])
    papers = []
    for item in items:
        title = item.get("title", [""])[0] if item.get("title") else ""
        if not title:
            continue

        # 轻度相关性检查: 标题中至少包含一个关键词的部分
        title_lower = title.lower()
        check_kws = [kw.lower() for kw in keywords[:2]]
        has_match = any(kw in title_lower for kw in check_kws if len(kw) > 3)
        # 如果标题不匹配, 检查摘要
        if not has_match:
            abstract = (item.get("abstract", "") or "").lower()
            has_match = any(kw in abstract for kw in check_kws if len(kw) > 3)
        if not has_match:
            continue

        authors = item.get("author", [])
        author_str = "; ".join(a.get("family", "") for a in authors[:3])
        if len(authors) > 3:
            author_str += f" et al."
        pub_date = item.get("published", {}).get("date-parts", [[]])[0]
        year = pub_date[0] if pub_date else ""

        papers.append({
            "title": title,
            "authors": author_str,
            "year": year,
            "citations": item.get("is-referenced-by-count", 0),
            "doi": item.get("DOI", ""),
            "type": item.get("type", ""),
            "abstract": (item.get("abstract", "") or "")[:300],
        })

    return {
        "topic": topic,
        "papers": papers,
        "total": data.get("message", {}).get("total-results", 0),
        "relevant_count": len(papers),
        "source": "Crossref",
        "status": "ok" if papers else "no_data"
    }


def collect_arxiv_papers(keywords: list[str], max_results: int = 10) -> dict:
    """arXiv API - 预印本论文搜索
    免费, 无需Key, 计算机科学/工程类
    """
    query = "+OR+".join(f"all:%22{kw.replace(' ', '+')}%22" for kw in keywords[:4])
    url = f"https://export.arxiv.org/api/query"
    params = {
        "search_query": query,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending"
    }

    import requests
    try:
        resp = requests.get(url, params=params,
                            headers={"User-Agent": "BM-Journal/1.0"},
                            timeout=15)
        if resp.status_code != 200:
            return {"papers": [], "status": "fetch_failed"}

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ElementTree.fromstring(resp.text)
        papers = []
        for entry in root.findall(".//atom:entry", ns):
            title = entry.findtext("atom:title", "", ns).strip().replace("\n", " ")
            summary = entry.findtext("atom:summary", "", ns).strip()[:300]
            pub = entry.findtext("atom:published", "", ns).strip()[:10]
            authors = [a.findtext("atom:name", "", ns) for a in entry.findall("atom:author", ns)[:3]]
            link_el = entry.find("atom:id", ns)
            link = link_el.text.strip() if link_el is not None else ""

            papers.append({
                "title": title,
                "authors": "; ".join(authors),
                "year": pub[:4] if pub else "",
                "summary": summary,
                "link": link,
                "source": "arXiv"
            })

        return {"papers": papers, "total": len(papers), "status": "ok" if papers else "no_data"}
    except Exception as e:
        log.warning(f"arXiv error: {e}")
        return {"papers": [], "status": "error"}


def collect_doaj_articles(keywords: list[str], page_size: int = 10) -> dict:
    """DOAJ API - 开放获取期刊论文搜索
    免费, 无需Key
    """
    query = " ".join(keywords[:3])
    from urllib.parse import quote
    encoded_query = quote(query)
    url = f"https://doaj.org/api/search/articles/{encoded_query}"
    params = {"pageSize": page_size}

    data = fetch_json(url, params=params, timeout=15, retries=1)
    if not data:
        return {"articles": [], "status": "no_data"}

    articles = []
    for result in data.get("results", []):
        bib = result.get("bibjson", {})
        articles.append({
            "title": bib.get("title", ""),
            "year": bib.get("year", ""),
            "journal": bib.get("journal", {}).get("title", ""),
            "abstract": bib.get("abstract", "")[:300],
            "authors": "; ".join(a.get("name", "") for a in bib.get("author", [])[:3]),
            "doi": bib.get("identifier", [{}])[0].get("id", "") if bib.get("identifier") else "",
            "source": "DOAJ"
        })

    return {
        "articles": articles,
        "total": data.get("total", 0),
        "status": "ok" if articles else "no_data"
    }


# ===================== 汇总 & 格式化 =====================

def collect_all_innovation() -> dict:
    """汇总所有创新/技术数据"""
    log.info("=== Collecting innovation & technology data ===")

    cache_key = "innovation_all"
    cached = cache_get(cache_key, "innovation", ttl=3600 * 24 * 5)  # 5天缓存: 保证周更(避免7d边界与CI周期重合)
    if cached:
        return cached

    results = {}

    # Crossref: 各创新主题的学术论文
    for topic, keywords in INNOVATION_TOPICS.items():
        log.info(f"  Crossref: {topic}")
        result = collect_crossref_papers(topic, keywords)
        results[topic] = result
        total = result.get("total", 0)
        count = len(result.get("papers", []))
        if count:
            log.info(f"    → {count} papers (total: {total})")
        time.sleep(1)  # Crossref rate limit

    # arXiv: 建筑科技预印本 (选3个核心主题)
    arxiv_topics = {
        "智能建造": ["smart construction", "construction automation", "construction robot"],
        "建筑能源": ["building energy efficiency", "net zero building"],
        "AI建筑设计": ["AI building design", "generative design architecture"],
    }
    arxiv_results = {}
    for topic, kws in arxiv_topics.items():
        log.info(f"  arXiv: {topic}")
        arxiv_results[topic] = collect_arxiv_papers(kws, max_results=5)
        time.sleep(3)  # arXiv rate limit (3s between requests)

    # DOAJ: 开放获取论文
    log.info(f"  DOAJ: building materials sustainability")
    doaj = collect_doaj_articles(["building", "materials", "sustainability"], page_size=10)

    # 汇总统计
    total_papers = sum(len(r.get("papers", [])) for r in results.values())
    topics_with_papers = sum(1 for r in results.values() if r.get("papers"))

    output = {
        "crossref": results,
        "arxiv": arxiv_results,
        "doaj": doaj,
        "total_papers_found": total_papers,
        "topics_with_papers": topics_with_papers,
        "total_topics": len(INNOVATION_TOPICS),
        "collected_at": datetime.now().isoformat(),
        "status": "ok" if total_papers > 0 else "no_data"
    }

    cache_set(cache_key, "innovation", output)
    save_raw("innovation", "all", output)

    log.info(f"Innovation: {topics_with_papers}/{len(INNOVATION_TOPICS)} topics with papers, "
             f"{total_papers} total")
    return output


def format_innovation_items(innovation_data: dict) -> list[dict]:
    """转化为期刊innovation板块格式, 含翻译和技术方向提炼"""
    from .translator import translate_text

    items = []

    # 技术方向映射: 从主题推断核心产品开发方向
    TECH_DIRECTIONS = {
        "低碳水泥": "开发低碳/零碳水泥配方，替代传统硅酸盐水泥；研究地质聚合物和LC3复合配方降低碳排放50%+",
        "自修复混凝土": "研发微生物/微胶囊自修复添加剂，延长混凝土结构寿命50%+；适用于基础设施和海洋工程",
        "3D打印建筑": "开发适用于大型3D打印的速凝特种水泥配方；优化打印路径和结构强度；降低建造成本30%+",
        "气凝胶保温": "开发低成本气凝胶复合保温板材；解决脆性问题提升施工性；目标导热系数<0.015 W/mK",
        "光伏一体化(BIPV)": "研发建筑外立面集成光伏组件；兼顾美观与发电效率；开发透明/彩色光伏玻璃",
        "大木结构(CLT)": "开发高强度CLT板材和连接节点系统；解决防火防潮技术难点；拓展中高层建筑应用",
        "模块化建筑": "设计标准化模块接口系统；开发轻量化结构板材；实现工厂预制率80%+的快速装配",
        "智能玻璃": "研发电致变色/热致变色智能调光玻璃；降低制造成本；集成建筑自动化控制系统",
        "再生钢材": "开发氢基直接还原铁(DRI-H2)炼钢工艺；提升废钢回收利用率；实现近零碳排放钢铁生产",
        "数字孪生": "构建建筑结构全生命周期数字孪生平台；集成IoT传感器实时监测；AI预测维护需求",
        "碳捕集建材": "开发CO2矿化养护混凝土技术；将工业废气转化为建材原料；实现碳负排放建材产品",
    }

    # 技术方向映射: 从主题推断核心产品开发方向
    TECH_DIRECTIONS = {
        "低碳水泥": "开发低碳/零碳水泥配方，替代传统硅酸盐水泥；研究地质聚合物和LC3复合配方降低碳排放50%+",
        "自修复混凝土": "研发微生物/微胶囊自修复添加剂，延长混凝土结构寿命50%+；适用于基础设施和海洋工程",
        "3D打印建筑": "开发适用于大型3D打印的速凝特种水泥配方；优化打印路径和结构强度；降低建造成本30%+",
        "气凝胶保温": "开发低成本气凝胶复合保温板材；解决脆性问题提升施工性；目标导热系数<0.015 W/mK",
        "光伏一体化(BIPV)": "研发建筑外立面集成光伏组件；兼顾美观与发电效率；开发透明/彩色光伏玻璃",
        "大木结构(CLT)": "开发高强度CLT板材和连接节点系统；解决防火防潮技术难点；拓展中高层建筑应用",
        "模块化建筑": "设计标准化模块接口系统；开发轻量化结构板材；实现工厂预制率80%+的快速装配",
        "智能玻璃": "研发电致变色/热致变色智能调光玻璃；降低制造成本；集成建筑自动化控制系统",
        "再生钢材": "开发氢基直接还原铁(DRI-H2)炼钢工艺；提升废钢回收利用率；实现近零碳排放钢铁生产",
        "数字孪生": "构建建筑结构全生命周期数字孪生平台；集成IoT传感器实时监测；AI预测维护需求",
        "碳捕集建材": "开发CO2矿化养护混凝土技术；将工业废气转化为建材原料；实现碳负排放建材产品",
    }

    # 主题中文标题映射（当翻译API不可用时的降级方案）
    TOPIC_ZH_TITLES = {
        "低碳水泥": "低碳水泥与地质聚合物",
        "自修复混凝土": "自修复混凝土技术",
        "3D打印建筑": "3D打印建筑技术",
        "气凝胶保温": "气凝胶保温材料",
        "光伏一体化(BIPV)": "建筑光伏一体化(BIPV)",
        "大木结构(CLT)": "大木结构(CLT)技术",
        "模块化建筑": "模块化与装配式建筑",
        "智能玻璃": "智能调光玻璃",
        "再生钢材": "再生钢材与绿色钢铁",
        "数字孪生": "建筑数字孪生",
        "碳捕集建材": "碳捕集建材技术",
        "智能建造": "智能建造与机器人",
        "建筑能源": "建筑能效优化",
        "AI建筑设计": "AI辅助建筑设计",
    }

    # 按主题聚合, 取论文最多的top 8
    topic_papers = []
    for topic, data in innovation_data.get("crossref", {}).items():
        papers = data.get("papers", [])
        relevant = data.get("relevant_count", len(papers))
        if papers:
            # 找最高引用的论文
            best = max(papers, key=lambda p: p.get("citations", 0))
            topic_papers.append({
                "topic": topic,
                "total_papers": relevant,
                "best_paper": best,
                "recent_count": len(papers)
            })

    topic_papers.sort(key=lambda x: -x["total_papers"])

    for tp in topic_papers[:8]:
        paper = tp["best_paper"]
        original_title = paper["title"][:80]

        # 翻译标题 (优先API翻译, 失败时用主题中文名)
        translated_title = translate_text(original_title)
        if translated_title == original_title:
            translated_title = TOPIC_ZH_TITLES.get(tp["topic"], original_title)

        # 提炼技术方向
        tech_direction = TECH_DIRECTIONS.get(tp["topic"], "")

        # 构建摘要(中文)
        summary = f"{tp['topic']}: 共{tp['total_papers']}篇相关论文(近期{tp['recent_count']}篇)。" \
                  f"代表研究: {paper['authors']}({paper['year']})，被引{paper['citations']}次。"

        items.append({
            "title": original_title,
            "title_zh": translated_title,
            "summary": summary,
            "tag": "innovation",
            "topic": tp["topic"],
            "paper_count": tp["total_papers"],
            "source": "Crossref/DOAJ",
            "doi": paper.get("doi", ""),
            "tech_direction": tech_direction,
        })

    # 补充arXiv预印本
    for topic, data in innovation_data.get("arxiv", {}).items():
        papers = data.get("papers", [])
        if papers:
            original_title = papers[0]["title"][:80]
            translated_title = translate_text(original_title)
            if translated_title == original_title:
                translated_title = TOPIC_ZH_TITLES.get(topic, original_title)
            items.append({
                "title": original_title,
                "title_zh": translated_title,
                "summary": f"{topic}: {len(papers)}篇预印本。最新: {papers[0]['authors']} - {translated_title[:50]}",
                "tag": "innovation",
                "topic": topic,
                "paper_count": len(papers),
                "source": "arXiv",
                "link": papers[0].get("link", ""),
                "tech_direction": TECH_DIRECTIONS.get(topic, ""),
            })

    return items[:10]


if __name__ == "__main__":
    data = collect_all_innovation()
    items = format_innovation_items(data)
    print(f"\nInnovation items: {len(items)}")
    for item in items[:5]:
        print(f"  [{item['topic']}] {item['title'][:60]} ({item['source']})")

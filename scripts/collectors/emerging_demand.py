"""新兴需求探测器
覆盖: 高增速未被关注的需求挖掘 + 未被满足的市场空白
策略: 交叉分析新闻RSS+社交信号, 发现异常增长信号
数据源: 复用news_aggregator + social_signals数据, 交叉分析
"""
import json, re
from datetime import datetime
from ..utils import cache_get, cache_set, save_raw, log


# ===================== 新兴需求信号检测 =====================

# 需求增长信号词
DEMAND_SIGNALS = {
    "surge": ["surge", "boom", "skyrocket", "soar", "rally", "spike", "surging", "booming",
              "爆发", "暴涨", "飙升", "猛增", "激增", "大幅增长"],
    "shortage": ["shortage", "deficit", "scarcity", "supply crunch", "shortfall", "undersupply",
                 "缺货", "短缺", "供不应求", "供应不足"],
    "emerging": ["emerging", "rising demand", "growing need", "untapped", "fastest-growing",
                 "blue ocean", "新兴", "蓝海", "空白市场", "新增长点"],
    "disruption": ["disrupt", "game changer", "revolutionary", "breakthrough", "transform",
                   "paradigm shift", "颠覆", "革新", "变革", "转型"],
    "policy_push": ["mandate", "requirement", "subsidy", "incentive", "stimulus", "fund",
                    "investment plan", "national strategy", "强制", "补贴", "激励", "专项基金"],
    "mega_project": ["mega project", "billion", "trillion", "national priority", "flagship",
                     "超级工程", "世纪工程", "国家战略", "旗舰项目"],
}

# 建材细分需求场景 (15个)
DEMAND_SCENARIOS = {
    "灾后重建": ["disaster", "reconstruction", "rebuilding", "hurricane", "earthquake", "flood",
                 "post-conflict", "灾后", "重建", "救灾", "废墟"],
    "数据中心": ["data center", "data centre", "hyperscale", "cooling", "raised floor",
                "数据中心", "算力基建"],
    "新能源基建": ["EV charging", "solar farm", "wind turbine", "battery factory", "renewable energy",
                  "新能源", "充电桩", "光伏电站", "风电", "储能"],
    "老龄化适老改造": ["aging population", "senior living", "accessible", "barrier-free", "elderly care",
                   "nursing home", "适老化", "无障碍", "养老", "银发经济"],
    "冷链物流": ["cold chain", "cold storage", "refrigerated", "cold logistics", "冷链", "冷库", "冷藏"],
    "海水淡化": ["desalination", "water treatment", "membrane", "water plant", "海水淡化", "净水"],
    "保障房/经济适用房": ["affordable housing", "social housing", "low-cost housing", "housing for all",
                     "保障房", "经济适用房", "公租房", "安居房"],
    "装配式建筑政策": ["prefab", "prefabrication", "modular construction", "off-site",
                   "装配式", "建筑工业化", "模块化建筑"],
    "中东超级工程": ["NEOM", "Vision 2030", "Saudi", "giga project", "Red Sea", "Qiddiya",
                 "Line", "Trojena", "Oxagon", "Saudi construction", "中东超级", "海湾工程"],
    "东南亚工业化": ["Southeast Asia", "ASEAN", "Vietnam factory", "Indonesia", "Thailand",
                 "Philippines", "industrial park", "东南亚", "东盟", "产业园"],
    "非洲城市化": ["Africa", "AfDB", "African city", "urbanization Africa", "Lagos", "Nairobi",
               "Kinshasa", "非洲", "非洲城市", "非洲基建"],
    "印度基建": ["India infrastructure", "Gati Shakti", "Smart Cities", "India highway",
              "Delhi-Mumbai", "India metro", "印度基建", "印度高铁", "印度城市"],
    "战后重建": ["Ukraine rebuild", "Gaza reconstruction", "post-war", "Marshall Plan",
              "donor conference", "war damage", "乌克兰重建", "加沙重建"],
    "被动房/零能耗": ["passive house", "Passivhaus", "net-zero building", "zero energy",
                 "nZEB", "被动房", "零能耗", "近零能耗"],
    "水基础设施": ["water infrastructure", "sewage", "wastewater", "pipeline", "water network",
              "water supply", "供水管网", "污水处理", "水利工程"],
}


def _scan_text_for_signals(text: str) -> dict:
    """扫描文本中的需求增长信号"""
    text_lower = text.lower()
    signals = {}
    for signal_type, keywords in DEMAND_SIGNALS.items():
        matched = [kw for kw in keywords if kw.lower() in text_lower]
        if matched:
            signals[signal_type] = matched
    return signals


def _scan_text_for_scenarios(text: str) -> list[str]:
    """扫描文本中的需求场景"""
    text_lower = text.lower()
    matched = []
    for scenario, keywords in DEMAND_SCENARIOS.items():
        if any(kw.lower() in text_lower for kw in keywords):
            matched.append(scenario)
    return matched


def detect_emerging_demands(news_data: dict = None, social_data: dict = None,
                             infra_data: dict = None) -> dict:
    """从新闻、社交和基建情报数据中探测新兴需求

    Args:
        news_data: news_aggregator的输出
        social_data: social_signals的输出
        infra_data: infra_intelligence的输出
    """
    log.info("=== Detecting emerging demands ===")

    cache_key = "emerging_demands"
    cached = cache_get(cache_key, "emerging", ttl=3600 * 24 * 3)
    if cached:
        return cached

    demand_signals = {}  # {scenario: {"count": N, "articles": [...], "signal_types": [...]}}

    # 扫描新闻文章
    if news_data:
        for article in news_data.get("articles", []):
            text = f"{article.get('title', '')} {article.get('description', '')}"
            signals = _scan_text_for_signals(text)
            scenarios = _scan_text_for_scenarios(text)

            for scenario in scenarios:
                if scenario not in demand_signals:
                    demand_signals[scenario] = {
                        "count": 0,
                        "articles": [],
                        "signal_types": set(),
                        "sources": set()
                    }
                demand_signals[scenario]["count"] += 1
                demand_signals[scenario]["articles"].append({
                    "title": article.get("title", "")[:80],
                    "source": article.get("source", ""),
                    "link": article.get("link", ""),
                    "categories": article.get("categories", [])
                })
                for sig_type in signals:
                    demand_signals[scenario]["signal_types"].add(sig_type)
                demand_signals[scenario]["sources"].add(article.get("source", ""))

    # 扫描Reddit帖子标题
    if social_data:
        reddit = social_data.get("reddit", {})
        for sub_data in reddit.get("subreddits", {}).values():
            for post in sub_data.get("posts", []):
                text = post.get("title", "")
                scenarios = _scan_text_for_scenarios(text)
                for scenario in scenarios:
                    if scenario not in demand_signals:
                        demand_signals[scenario] = {
                            "count": 0, "articles": [],
                            "signal_types": set(), "sources": set()
                        }
                    demand_signals[scenario]["count"] += 1
                    demand_signals[scenario]["articles"].append({
                        "title": text[:80],
                        "source": f"Reddit/{post.get('subreddit', '')}",
                        "link": post.get("url", ""),
                        "categories": ["social"]
                    })
                    demand_signals[scenario]["sources"].add("Reddit")

    # 扫描基建情报文章 (infra_intelligence)
    if infra_data:
        for article in infra_data.get("articles", []):
            text = f"{article.get('title', '')} {article.get('summary', '')}"
            signals = _scan_text_for_signals(text)
            scenarios = _scan_text_for_scenarios(text)

            for scenario in scenarios:
                if scenario not in demand_signals:
                    demand_signals[scenario] = {
                        "count": 0, "articles": [],
                        "signal_types": set(), "sources": set()
                    }
                demand_signals[scenario]["count"] += 1
                demand_signals[scenario]["articles"].append({
                    "title": article.get("title", "")[:80],
                    "source": f"基建情报/{article.get('tag', '')}",
                    "link": article.get("link", ""),
                    "categories": [article.get("region", "")]
                })
                for sig_type in signals:
                    demand_signals[scenario]["signal_types"].add(sig_type)
                demand_signals[scenario]["sources"].add(article.get("source", "基建情报"))

    # 转换为可序列化格式
    results = []
    for scenario, data in demand_signals.items():
        results.append({
            "scenario": scenario,
            "signal_count": data["count"],
            "articles": data["articles"][:5],
            "signal_types": list(data["signal_types"]),
            "sources": list(data["sources"]),
            "strength": "strong" if data["count"] >= 2 else "medium"
        })

    # 排序: 信号强度 + 出现次数
    results.sort(key=lambda x: (-x["signal_count"], x["strength"] != "strong"))

    # 同时生成"未被满足需求"洞察
    unmet_needs = _detect_unmet_needs(news_data)

    output = {
        "emerging_demands": results,
        "unmet_needs": unmet_needs,
        "total_signals": len(results),
        "strong_signals": sum(1 for r in results if r["strength"] == "strong"),
        "collected_at": datetime.now().isoformat(),
        "status": "ok" if results else "no_data"
    }

    cache_set(cache_key, "emerging", output)
    save_raw("emerging", "demands", output)

    log.info(f"Emerging demands: {len(results)} scenarios "
             f"({sum(1 for r in results if r['strength']=='strong')} strong), "
             f"{len(unmet_needs)} unmet needs")
    return output


def _detect_unmet_needs(news_data: dict = None) -> list[dict]:
    """检测未被满足的市场需求"""
    if not news_data:
        return []

    unmet = []
    unmet_keywords = ["not available", "lack of", "insufficient", "gap", "underserved",
                      "no solution", "missing", "unmet", "短缺", "空白", "缺乏"]

    for article in news_data.get("articles", []):
        text = f"{article.get('title', '')} {article.get('description', '')}".lower()
        matched = [kw for kw in unmet_keywords if kw in text]
        if matched:
            unmet.append({
                "title": article.get("title", "")[:80],
                "source": article.get("source", ""),
                "keywords": matched,
                "categories": article.get("categories", [])
            })

    return unmet[:10]


def format_emerging_demands(emerging_data: dict) -> list[dict]:
    """转化为期刊可用的新兴需求洞察 (输出数量为3的倍数)"""
    items = []

    for demand in emerging_data.get("emerging_demands", []):
        if demand["signal_count"] < 1:
            continue

        signal_desc = ", ".join(demand["signal_types"][:3]) if demand["signal_types"] else "需求信号"
        articles_preview = demand["articles"][:2]

        items.append({
            "name": demand["scenario"],
            "signal_count": demand["signal_count"],
            "strength": demand["strength"],
            "signal_types": demand["signal_types"],
            "description": f"检测到{demand['signal_count']}条{signal_desc}信号。"
                           f"来源: {', '.join(demand['sources'][:3])}。",
            "example_articles": [
                {"title": a["title"], "source": a["source"]}
                for a in articles_preview
            ]
        })

    # 补充未满足需求 (最多5条)
    for unmet in emerging_data.get("unmet_needs", [])[:5]:
        items.append({
            "name": "未满足需求",
            "signal_count": 1,
            "strength": "medium",
            "signal_types": ["gap"],
            "description": f"{unmet['title']} ({unmet['source']}) - 关键词: {', '.join(unmet['keywords'][:3])}",
            "example_articles": [
                {"title": unmet["title"], "source": unmet["source"]}
            ]
        })

    # 确保输出为3的倍数 (最少3条, 最多12条)
    if items:
        target = max(3, min(12, ((len(items) + 2) // 3) * 3))
        # 如果不够3的倍数,从emerging_demands中补充weak信号
        while len(items) < target:
            added = False
            for demand in emerging_data.get("emerging_demands", []):
                name = demand["scenario"]
                if not any(it["name"] == name for it in items):
                    items.append({
                        "name": name,
                        "signal_count": demand["signal_count"],
                        "strength": "weak",
                        "signal_types": demand["signal_types"],
                        "description": f"趋势观察: {name}。来源: {', '.join(demand['sources'][:2]) or '综合'}。",
                        "example_articles": [
                            {"title": a["title"], "source": a["source"]}
                            for a in demand["articles"][:1]
                        ]
                    })
                    added = True
                    break
            if not added:
                break
        # 截断到3的倍数
        remainder = len(items) % 3
        if remainder:
            items = items[:len(items) - remainder]

    return items[:12]


if __name__ == "__main__":
    # 测试: 加载已有的新闻和社交数据
    from pathlib import Path
    data_dir = Path(__file__).parent.parent.parent / "data" / "raw"

    news = None
    social = None

    news_file = data_dir / "news" / "all_articles.json"
    if news_file.exists():
        with open(news_file) as f:
            news = json.load(f)

    social_file = data_dir / "social_signals" / "reddit_trends.json"
    if social_file.exists():
        with open(social_file) as f:
            social = json.load(f)

    data = detect_emerging_demands(news, social)
    items = format_emerging_demands(data)
    print(f"\nEmerging demands: {len(items)}")
    for item in items[:5]:
        marker = "🔥" if item["strength"] == "strong" else ("⬆" if item["strength"] == "medium" else "→")
        print(f"  {marker} {item['name']} (x{item['signal_count']}) [{', '.join(item['signal_types'][:2])}]")

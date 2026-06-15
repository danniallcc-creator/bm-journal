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
    "surge": ["surge", "boom", "skyrocket", "soar", "rally", "spike", "爆发", "暴涨", "飙升"],
    "shortage": ["shortage", "deficit", "scarcity", "supply crunch", "缺货", "短缺", "供不应求"],
    "emerging": ["emerging", "rising demand", "growing need", "untapped", "新兴", "蓝海", "空白市场"],
    "disruption": ["disrupt", "game changer", "revolutionary", "breakthrough", "颠覆", "革新"],
    "policy_push": ["mandate", "requirement", "subsidy", "incentive", "stimulus", "强制", "补贴", "激励"],
}

# 建材细分需求场景
DEMAND_SCENARIOS = {
    "灾后重建": ["disaster", "reconstruction", "rebuilding", "hurricane", "earthquake", "flood",
                 "灾后", "重建", "救灾"],
    "数据中心": ["data center", "hyperscale", "cooling", "raised floor", "数据中心"],
    "新能源基建": ["EV charging", "solar farm", "wind turbine", "battery factory",
                  "新能源", "充电桩", "光伏电站"],
    "老龄化适老改造": ["aging population", "senior living", "accessible", "barrier-free",
                   "适老化", "无障碍", "养老"],
    "冷链物流": ["cold chain", "cold storage", "refrigerated", "冷链", "冷库"],
    "海水淡化": ["desalination", "water treatment", "membrane", "海水淡化"],
    "保障房/经济适用房": ["affordable housing", "social housing", "保障房", "经济适用房", "公租房"],
    "装配式建筑政策": ["prefab mandate", "prefabrication policy", "装配式", "建筑工业化"],
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


def detect_emerging_demands(news_data: dict = None, social_data: dict = None) -> dict:
    """从新闻和社交数据中探测新兴需求

    Args:
        news_data: news_aggregator的输出
        social_data: social_signals的输出
    """
    log.info("=== Detecting emerging demands ===")

    cache_key = "emerging_demands"
    cached = cache_get(cache_key, "emerging", ttl=3600 * 24 * 5)
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

    # 转换为可序列化格式
    results = []
    for scenario, data in demand_signals.items():
        results.append({
            "scenario": scenario,
            "signal_count": data["count"],
            "articles": data["articles"][:5],
            "signal_types": list(data["signal_types"]),
            "sources": list(data["sources"]),
            "strength": "strong" if data["count"] >= 3 else ("medium" if data["count"] >= 2 else "weak")
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
    """转化为期刊可用的新兴需求洞察"""
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

    # 补充未满足需求
    for unmet in emerging_data.get("unmet_needs", [])[:3]:
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

    return items[:10]


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

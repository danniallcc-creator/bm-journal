"""社交信号采集器 - 建材品类搜索趋势
覆盖: Google Trends(pytrends) + YouTube搜索量 + Reddit热度
策略: 35个二级品类 x 2-4关键词, 每周采集一次
注意: pytrends 429风险高, 需要间隔+限量; YouTube有配额限制
"""
import json, time, re
from datetime import datetime, timedelta
from ..config import FRED_API_KEY
from ..utils import fetch_json, cache_get, cache_set, save_raw, log, safe_float, pct_change

# YouTube API Key (从环境变量)
import os
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

# ===================== 关键词库 =====================

# 35个二级品类 → 搜索关键词 (英文为主, 用于全球趋势)
CATEGORY_KEYWORDS = {
    "地板及配件": ["SPC flooring", "LVT flooring", "vinyl flooring", "engineered wood flooring"],
    "瓷砖及配件": ["sintered stone", "porcelain tile", "large format tile", "ceramic tile"],
    "建筑板材": ["sandwich panel", "cement board", "aluminum composite panel", "ACP panel"],
    "石材": ["natural stone slab", "quartz countertop", "artificial stone"],
    "浴室和厨房产品": ["prefab bathroom", "modular kitchen", "smart toilet", "rainfall shower"],
    "门、窗及其配件": ["aluminum window", "UPVC window", "smart door lock", "sliding door"],
    "活动房屋与钢结构": ["container house", "prefab house", "steel structure building", "modular building"],
    "木材": ["CLT timber", "cross laminated timber", "plywood", "engineered lumber"],
    "砖石材料": ["autoclaved aerated concrete", "AAC block", "lightweight concrete"],
    "建筑工业玻璃": ["Low-E glass", "smart glass", "switchable glass", "photovoltaic glass"],
    "墙纸/墙板": ["WPC wall panel", "fluted panel", "wall cladding", "3D wall panel"],
    "塑料建材": ["WPC decking", "composite decking", "PVC profile"],
    "防水材料": ["waterproof membrane", "TPO roofing", "EPDM membrane"],
    "隔热材料": ["aerogel insulation", "spray foam insulation", "EPS panel"],
    "防火材料": ["fire rated board", "magnesium oxide board", "intumescent coating"],
    "天花板": ["acoustic ceiling", "metal ceiling", "stretch ceiling"],
    "幕墙配件": ["curtain wall system", "spider fitting", "structural glazing"],
    "电梯和自动扶梯": ["home elevator", "machine room less elevator", "residential lift"],
    "梯子及脚手架": ["aluminum scaffolding", "ringlock scaffolding"],
    "空调系统及配件": ["VRF system", "heat pump", "mini split AC", "HVAC duct"],
    "户外设施类": ["outdoor gazebo", "pergola", "garden fountain"],
    "楼梯及楼梯配件": ["floating staircase", "glass railing", "spiral staircase"],
    "土工材料": ["geotextile", "geogrid", "geomembrane"],
    "壁炉、炉灶": ["bioethanol fireplace", "electric fireplace", "pellet stove"],
    "塑料管": ["PPR pipe", "HDPE pipe", "PVC pipe fitting"],
    "隔音材料": ["acoustic panel", "soundproofing", "acoustic foam"],
}


def collect_google_trends(keywords: list[str], timeframe: str = "today 3-m",
                          geo: str = "") -> dict:
    """Google Trends via pytrends (非官方, 429风险)

    Args:
        keywords: 最多5个关键词
        timeframe: 时间范围
        geo: 地区代码(空=全球)
    """
    result = {"interest_over_time": [], "related_queries": {}, "status": "ok"}

    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl='en-US', tz=360, timeout=(10, 25),
                           requests_args={"headers": {
                               "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
                           }})

        # interest_over_time (趋势数据)
        pytrends.build_payload(keywords[:5], cat=0, timeframe=timeframe, geo=geo)
        df = pytrends.interest_over_time()
        if not df.empty:
            for kw in keywords[:5]:
                if kw in df.columns:
                    values = df[kw].tolist()
                    # 计算最近4周vs前4周的增长率
                    if len(values) >= 8:
                        recent = sum(values[-4:]) / 4
                        previous = sum(values[-8:-4]) / 4
                        growth = pct_change(recent, previous) if previous > 0 else None
                    else:
                        recent = sum(values[-4:]) / max(len(values[-4:]), 1)
                        growth = None

                    result["interest_over_time"].append({
                        "keyword": kw,
                        "avg_recent": round(recent, 1),
                        "growth_4w": growth,
                        "data_points": len(values),
                        "trend": "up" if growth and growth > 10 else ("down" if growth and growth < -10 else "stable")
                    })

        # related_queries (发现新兴搜索词)
        try:
            related = pytrends.related_queries()
            for kw, data in related.items():
                if data.get("rising") is not None and not data["rising"].empty:
                    rising = data["rising"].head(5)
                    result["related_queries"][kw] = [
                        {"query": row["query"], "value": str(row["value"])}
                        for _, row in rising.iterrows()
                    ]
        except Exception:
            pass

    except ImportError:
        result["status"] = "pytrends_not_installed"
        log.warning("pytrends not installed, skipping Google Trends")
    except Exception as e:
        err_str = str(e)
        if "429" in err_str or "Too Many Requests" in err_str:
            result["status"] = "rate_limited"
            log.warning("Google Trends rate limited (429)")
        else:
            result["status"] = "error"
            log.warning(f"Google Trends error: {err_str[:100]}")

    return result


def _check_pytrends_available() -> bool:
    """检查pytrends是否已安装且可用, 未安装则自动安装"""
    try:
        from pytrends.request import TrendReq
        return True
    except ImportError:
        log.info("pytrends not found, attempting auto-install...")
        import subprocess, sys
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "pytrends", "-q"],
                timeout=60
            )
            from pytrends.request import TrendReq
            log.info("pytrends auto-installed successfully")
            return True
        except Exception as e:
            log.warning(f"pytrends auto-install failed: {e}")
            return False


def collect_google_trends_batch() -> dict:
    """批量采集所有品类的Google Trends数据
    策略: 每次5个关键词, 间隔5分钟, 限制15组(75关键词)
    """
    log.info("=== Collecting Google Trends (batch) ===")

    cache_key = "gtrends_batch"
    cached = cache_get(cache_key, "social_signals", ttl=3600 * 24 * 5)  # 5天缓存
    if cached:
        return cached

    # 先检查pytrends是否可用, 避免无效循环
    if not _check_pytrends_available():
        log.warning("pytrends not installed, skipping all Google Trends collection")
        return {"results": {}, "groups_attempted": 0,
                "collected_at": datetime.now().isoformat(),
                "status": "pytrends_not_installed"}

    # 环境变量开关：CI 环境下可跳过 Google Trends 采集 (避免429/超时)
    if os.environ.get("SKIP_GTRENDS", "").lower() in ("1", "true", "yes"):
        log.warning("SKIP_GTRENDS=1, skipping Google Trends collection")
        return {"results": {}, "groups_attempted": 0,
                "collected_at": datetime.now().isoformat(),
                "status": "skipped_by_env"}

    # 构建关键词组 (每组5个)
    groups = []
    for category, keywords in CATEGORY_KEYWORDS.items():
        for i in range(0, len(keywords), 5):
            groups.append({
                "category": category,
                "keywords": keywords[i:i+5]
            })

    # 限制批次数量 (避免429)
    max_groups = 15
    if len(groups) > max_groups:
        log.info(f"Limiting to {max_groups}/{len(groups)} groups to avoid rate limiting")
        groups = groups[:max_groups]

    all_results = {}
    groups_done = 0
    for idx, group in enumerate(groups):
        log.info(f"  GTrends group {idx+1}/{max_groups}: {group['category']}")
        result = collect_google_trends(group["keywords"])

        cat = group["category"]
        if cat not in all_results:
            all_results[cat] = {"keywords": [], "related": {}}

        all_results[cat]["keywords"].extend(result.get("interest_over_time", []))
        all_results[cat]["related"].update(result.get("related_queries", {}))

        if result["status"] == "rate_limited":
            log.warning("Rate limited, stopping Google Trends collection")
            break

        groups_done += 1

        # 间隔等待 (避免429)
        if idx < len(groups) - 1:
            wait = 120 + (idx % 3) * 60  # 120-300秒随机间隔
            log.info(f"  Waiting {wait}s before next request...")
            time.sleep(wait)

    output = {
        "results": all_results,
        "groups_attempted": groups_done,
        "collected_at": datetime.now().isoformat(),
        "status": "ok" if all_results else "no_data"
    }

    cache_set(cache_key, "social_signals", output)
    save_raw("social_signals", "google_trends", output)
    return output


# ===================== YouTube 趋势 =====================

def collect_youtube_trends(keywords: list[str]) -> dict:
    """YouTube Data API v3 - 搜索近1周高播放量视频
    配额: 10000单位/天, search.list=100单位/次 → 约100次搜索/天
    """
    if not YOUTUBE_API_KEY:
        log.warning("YOUTUBE_API_KEY not set, skipping YouTube trends")
        return {"results": {}, "status": "no_key"}

    log.info("=== Collecting YouTube trends ===")

    cache_key = "youtube_trends"
    cached = cache_get(cache_key, "social_signals", ttl=3600 * 24 * 5)
    if cached:
        return cached

    one_week_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    results = {}

    for keyword in keywords[:30]:  # 限制30个搜索 (3000单位)
        params = {
            "part": "snippet",
            "q": keyword,
            "order": "viewCount",
            "publishedAfter": one_week_ago,
            "type": "video",
            "maxResults": 5,
            "key": YOUTUBE_API_KEY,
            "relevanceLanguage": "en"
        }
        data = fetch_json("https://www.googleapis.com/youtube/v3/search",
                          params=params, timeout=15)
        if data and "items" in data:
            videos = []
            for item in data["items"]:
                videos.append({
                    "title": item["snippet"]["title"],
                    "channel": item["snippet"]["channelTitle"],
                    "video_id": item["id"]["videoId"]
                })
            results[keyword] = {
                "video_count": len(videos),
                "top_videos": videos[:3]
            }
            log.info(f"  YouTube '{keyword}': {len(videos)} videos")
        time.sleep(0.5)

    output = {
        "results": results,
        "keywords_searched": min(len(keywords), 30),
        "collected_at": datetime.now().isoformat(),
        "status": "ok" if results else "no_data"
    }

    cache_set(cache_key, "social_signals", output)
    save_raw("social_signals", "youtube_trends", output)
    return output


# ===================== Reddit 热度 (RSS方式, 免OAuth) =====================

def _reddit_fetch_rss(sub: str) -> list[dict]:
    """Reddit RSS feed, 无需OAuth认证
    URL: https://www.reddit.com/r/{sub}/.rss (Atom XML)
    """
    import requests as _requests
    from xml.etree import ElementTree
    url = f"https://www.reddit.com/r/{sub}/.rss"
    headers = {"User-Agent": "BM-Journal/1.0 (Building Materials Research)"}
    try:
        resp = _requests.get(url, headers=headers, timeout=12)
        if resp.status_code != 200:
            log.warning(f"Reddit RSS HTTP {resp.status_code}: r/{sub}")
            return []

        # Atom XML解析
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ElementTree.fromstring(resp.text)
        posts = []
        for entry in root.findall("atom:entry", ns):
            title = entry.findtext("atom:title", "", ns).strip()
            link_el = entry.find("atom:link", ns)
            link = link_el.get("href", "") if link_el is not None else ""
            content = entry.findtext("atom:content", "", ns)
            # 从content中提取score (Reddit RSS content中有score信息)
            score = 0
            import re
            score_match = re.search(r'(\d+)\s*(?:points?|upvotes?)', content, re.I)
            if score_match:
                score = int(score_match.group(1))
            comment_match = re.search(r'(\d+)\s*comments?', content, re.I)
            num_comments = int(comment_match.group(1)) if comment_match else 0
            if title:
                posts.append({
                    "title": title[:200],
                    "score": score,
                    "num_comments": num_comments,
                    "subreddit": sub,
                    "url": link
                })
        return posts
    except Exception as e:
        log.warning(f"Reddit RSS error r/{sub}: {e}")
    return []


def collect_reddit_trends() -> dict:
    """Reddit RSS - 建筑/装修subreddit热帖分析 (免OAuth)
    快速失败策略: 12s超时, 无重试, 单个subreddit失败不阻塞
    """
    log.info("=== Collecting Reddit trends (RSS) ===")

    cache_key = "reddit_trends"
    cached = cache_get(cache_key, "social_signals", ttl=3600 * 24 * 3)
    if cached:
        return cached

    subreddits = [
        "HomeImprovement", "DIY", "Renovation",
        "construction", "architecture", "InteriorDesign"
    ]

    results = {}

    for sub in subreddits:
        posts = _reddit_fetch_rss(sub)
        if posts:
            results[sub] = {
                "posts": posts,
                "total": len(posts),
                "avg_score": round(sum(p["score"] for p in posts) / max(len(posts), 1), 1)
            }
            log.info(f"  Reddit r/{sub}: {len(posts)} posts, avg score {results[sub]['avg_score']}")
        time.sleep(1.5)  # 降低频率避免429

    # 提取建材相关关键词频率
    building_keywords = [
        "floor", "tile", "bathroom", "kitchen", "window", "door", "roof",
        "insulation", "concrete", "wood", "drywall", "paint", "plumbing",
        "cabinet", "countertop", "shower", "deck", "fence", "siding",
        "solar", "heat pump", "HVAC", "foundation", "framing"
    ]
    keyword_freq = {}
    for sub_data in results.values():
        for post in sub_data.get("posts", []):
            title_lower = post["title"].lower()
            for kw in building_keywords:
                if kw.lower() in title_lower:
                    keyword_freq[kw] = keyword_freq.get(kw, 0) + 1

    output = {
        "subreddits": results,
        "keyword_frequency": dict(sorted(keyword_freq.items(), key=lambda x: -x[1])),
        "collected_at": datetime.now().isoformat(),
        "status": "ok" if results else "no_data"
    }

    cache_set(cache_key, "social_signals", output)
    save_raw("social_signals", "reddit_trends", output)
    return output


# ===================== 汇总 & 格式化 =====================

def collect_all_social_signals() -> dict:
    """汇总所有社交信号"""
    reddit = collect_reddit_trends()

    # Google Trends (有条件执行, 避免429)
    gtrends = {"results": {}, "status": "skipped"}
    try:
        gtrends = collect_google_trends_batch()
    except Exception as e:
        log.warning(f"Google Trends batch failed: {e}")

    # YouTube (需要Key)
    all_keywords = []
    for kws in CATEGORY_KEYWORDS.values():
        all_keywords.extend(kws[:2])
    youtube = collect_youtube_trends(all_keywords[:30])

    return {
        "google_trends": gtrends,
        "youtube": youtube,
        "reddit": reddit,
        "collected_at": datetime.now().isoformat()
    }


def format_product_trends(social_data: dict) -> list[dict]:
    """将社交信号转化为期刊 trends 板块格式
    筛选增速最高的品类作为"趋势产品"
    """
    trends = []
    gtrends = social_data.get("google_trends", {}).get("results", {})

    for category, data in gtrends.items():
        keywords = data.get("keywords", [])
        # 找增速最高的关键词
        best = max(
            [k for k in keywords if k.get("growth_4w") is not None],
            key=lambda k: k["growth_4w"] or 0,
            default=None
        )
        if best and best.get("growth_4w") and best["growth_4w"] > 15:
            # 收集该品类所有关键词的信号
            signals = []
            for kw_data in keywords:
                if kw_data.get("growth_4w") is not None:
                    signals.append({
                        "platform": "Google",
                        "growth": kw_data["growth_4w"]
                    })
                    break

            # 补充Reddit信号
            reddit_kw = social_data.get("reddit", {}).get("keyword_frequency", {})
            for rkw, count in reddit_kw.items():
                if any(rkw.lower() in k.lower() for k in CATEGORY_KEYWORDS.get(category, [])):
                    signals.append({
                        "platform": "Reddit",
                        "growth": count * 10  # 粗略映射
                    })

            if signals:
                trends.append({
                    "name": category,
                    "category": category,
                    "description": f"Google搜索趋势显示'{best['keyword']}'近4周增长{best['growth_4w']:.0f}%",
                    "drivers": [category],
                    "socialSignals": signals,
                    "satisfaction": 50  # 默认值, P2阶段优化
                })

    # 按增速排序, 取top 8
    trends.sort(key=lambda t: max((s.get("growth", 0) for s in t.get("socialSignals", [])), default=0), reverse=True)
    return trends[:8]


if __name__ == "__main__":
    data = collect_all_social_signals()
    trends = format_product_trends(data)
    print(f"\nTop trending categories: {len(trends)}")
    for t in trends[:5]:
        print(f"  {t['name']}: {[s['growth'] for s in t['socialSignals']]}")
    print(json.dumps(data.get("reddit", {}).get("keyword_frequency", {}),
                      ensure_ascii=False, indent=2))

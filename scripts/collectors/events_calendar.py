"""事件日历采集器
覆盖: 行业展会 + 央行政策会议 + 重要政策发布日 + 招投标节点
策略: 内置核心事件库(年度更新) + 央行日历API + 动态抓取
"""
import json
from datetime import datetime, timedelta, date
from ..utils import cache_get, cache_set, save_raw, log


# ===================== 内置事件库 =====================

# 行业重要展会 (年度, 需手动更新具体日期)
TRADE_SHOWS = [
    # 全球顶级展会
    {"name": "bauma (慕尼黑国际工程机械展)", "location": "慕尼黑, 德国",
     "frequency": "triennial", "next_dates": ["2025-04-07", "2025-04-13"],
     "categories": ["工程机械", "建材设备"], "importance": "top",
     "website": "https://www.bauma.de"},
    {"name": "Canton Fair 广交会 (春季)", "location": "广州, 中国",
     "frequency": "annual", "next_dates": ["2027-04-15", "2027-05-05"],
     "categories": ["综合贸易", "建材出口"], "importance": "top",
     "website": "https://www.cantonfair.org.cn"},
    {"name": "Canton Fair 广交会 (秋季)", "location": "广州, 中国",
     "frequency": "annual", "next_dates": ["2026-10-15", "2026-11-04"],
     "categories": ["综合贸易", "建材出口"], "importance": "top",
     "website": "https://www.cantonfair.org.cn"},
    {"name": "The Big 5 (迪拜五大行业展)", "location": "迪拜, 阿联酋",
     "frequency": "annual", "next_dates": ["2026-12-08", "2026-12-11"],
     "categories": ["建材", "建筑技术"], "importance": "high",
     "website": "https://www.thebig5.ae"},
    {"name": "World of Concrete", "location": "拉斯维加斯, 美国",
     "frequency": "annual", "next_dates": ["2027-01-19", "2027-01-21"],
     "categories": ["混凝土", "水泥"], "importance": "high",
     "website": "https://www.worldofconcrete.com"},
    {"name": "IBS (International Builders' Show)", "location": "美国 (每年变动)",
     "frequency": "annual", "next_dates": ["2027-02-17", "2027-02-19"],
     "categories": ["住宅建筑", "建材"], "importance": "high",
     "website": "https://www.buildersshow.com"},
    {"name": "BATIMAT (巴黎国际建材展)", "location": "巴黎, 法国",
     "frequency": "biennial", "next_dates": ["2026-09-28", "2026-10-03"],
     "categories": ["建材", "建筑创新"], "importance": "high",
     "website": "https://www.batimat.com"},
    {"name": "Greenbuild", "location": "美国 (每年变动)",
     "frequency": "annual", "next_dates": ["2026-11-03", "2026-11-05"],
     "categories": ["绿色建筑", "可持续建材"], "importance": "medium",
     "website": "https://www.greenbuild.org"},
    {"name": "Architct@Expo", "location": "上海, 中国",
     "frequency": "annual", "next_dates": ["2026-08-15", "2026-08-17"],
     "categories": ["建筑设计", "建材"], "importance": "medium",
     "website": ""},
    {"name": "India Stonemart", "location": "斋浦尔, 印度",
     "frequency": "biennial", "next_dates": ["2027-02-01", "2027-02-04"],
     "categories": ["石材", "大理石"], "importance": "medium",
     "website": ""},
    {"name": "Coverings (瓷砖石材展)", "location": "美国 (每年变动)",
     "frequency": "annual", "next_dates": ["2027-04-20", "2027-04-23"],
     "categories": ["瓷砖", "石材", "地板"], "importance": "medium",
     "website": "https://www.coverings.com"},
    {"name": "LIGNA (汉诺威木工机械展)", "location": "汉诺威, 德国",
     "frequency": "biennial", "next_dates": ["2027-05-22", "2027-05-26"],
     "categories": ["木材加工", "木工机械"], "importance": "high",
     "website": "https://www.ligna.de"},
    {"name": "GlassBuild", "location": "美国",
     "frequency": "annual", "next_dates": ["2026-10-27", "2026-10-29"],
     "categories": ["建筑玻璃", "门窗"], "importance": "medium",
     "website": "https://www.glassbuild.com"},
    {"name": "Xiamen Stone Fair (厦门石材展)", "location": "厦门, 中国",
     "frequency": "annual", "next_dates": ["2027-03-16", "2027-03-19"],
     "categories": ["石材", "花岗岩", "大理石"], "importance": "high",
     "website": "https://www.stonefair.org.cn"},
]

# 央行政策会议日期 (2026年, FOMC/ECB等固定日程)
CENTRAL_BANK_DATES_2026 = [
    # Fed FOMC
    {"event": "FOMC利率决议", "institution": "美联储", "dates": [
        "2026-01-28", "2026-03-18", "2026-05-06", "2026-06-17",
        "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16"
    ]},
    # ECB
    {"event": "ECB利率决议", "institution": "欧洲央行", "dates": [
        "2026-01-22", "2026-03-05", "2026-04-16", "2026-06-04",
        "2026-07-23", "2026-09-10", "2026-10-22", "2026-12-10"
    ]},
    # BOJ
    {"event": "BOJ利率决议", "institution": "日本央行", "dates": [
        "2026-01-23", "2026-03-19", "2026-04-30", "2026-06-18",
        "2026-07-30", "2026-09-18", "2026-10-29", "2026-12-18"
    ]},
    # BOE
    {"event": "BOE利率决议", "institution": "英国央行", "dates": [
        "2026-02-05", "2026-03-19", "2026-05-07", "2026-06-18",
        "2026-08-06", "2026-09-17", "2026-11-05", "2026-12-17"
    ]},
    # PBoC LPR
    {"event": "LPR报价", "institution": "中国人民银行", "dates": [
        "2026-01-20", "2026-02-20", "2026-03-20", "2026-04-20",
        "2026-05-20", "2026-06-20", "2026-07-20", "2026-08-20",
        "2026-09-20", "2026-10-20", "2026-11-20", "2026-12-20"
    ]},
]


def _get_upcoming_events(days_ahead: int = 90) -> list[dict]:
    """获取未来N天内的所有事件"""
    today = date.today()
    end_date = today + timedelta(days=days_ahead)
    upcoming = []

    # 展会
    for show in TRADE_SHOWS:
        found_upcoming = False
        for date_str in show.get("next_dates", []):
            try:
                event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                if today <= event_date <= end_date:
                    upcoming.append({
                        "name": show["name"],
                        "date": date_str,
                        "location": show["location"],
                        "type": "trade_show",
                        "importance": show.get("importance", "medium"),
                        "categories": show.get("categories", []),
                        "website": show.get("website", ""),
                        "days_away": (event_date - today).days
                    })
                    found_upcoming = True
            except ValueError:
                pass

        # 日期推算: 如硬编码日期全部过期,按频率自动推算下一届
        if not found_upcoming and show.get("next_dates"):
            freq_years = {"annual": 1, "biennial": 2, "triennial": 3}.get(
                show.get("frequency", "annual"), 1
            )
            try:
                last_date = datetime.strptime(show["next_dates"][-1], "%Y-%m-%d").date()
                # 从最后已知日期向后推算,直到找到未来日期
                projected = last_date
                for _ in range(10):  # 最多推10个周期
                    projected = projected.replace(year=projected.year + freq_years)
                    if today <= projected <= end_date:
                        upcoming.append({
                            "name": show["name"] + " (预估)",
                            "date": projected.strftime("%Y-%m-%d"),
                            "location": show["location"],
                            "type": "trade_show",
                            "importance": show.get("importance", "medium"),
                            "categories": show.get("categories", []),
                            "website": show.get("website", ""),
                            "days_away": (projected - today).days
                        })
                        break
                    elif projected > end_date:
                        break
            except ValueError:
                pass

    # 央行会议
    current_year = today.year
    for bank in CENTRAL_BANK_DATES_2026:
        bank_found = False
        for date_str in bank["dates"]:
            try:
                event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                # 如果当前年份超过2026,尝试同月同日推算到当前年
                if current_year > 2026:
                    try:
                        event_date = event_date.replace(year=current_year)
                    except ValueError:
                        continue  # 跳过不合法日期(如2月29)
                if today <= event_date <= end_date:
                    upcoming.append({
                        "name": bank["event"],
                        "date": event_date.strftime("%Y-%m-%d"),
                        "location": bank["institution"],
                        "type": "central_bank",
                        "importance": "high",
                        "categories": ["货币政策", "利率"],
                        "website": "",
                        "days_away": (event_date - today).days
                    })
                    bank_found = True
            except ValueError:
                pass

    # 按日期排序
    upcoming.sort(key=lambda x: x["date"])
    return upcoming


def collect_events_calendar() -> dict:
    """采集事件日历

    Returns:
        {
            "events": [{"name", "date", "location", "type", "importance", "days_away"}],
            "total": 25,
            "trade_shows": 5,
            "central_bank": 20,
            "status": "ok"
        }
    """
    log.info("=== Collecting events calendar ===")

    cache_key = "events_calendar"
    cached = cache_get(cache_key, "events", ttl=3600 * 24 * 5)  # 5天缓存: 保证周更(避免7d边界与CI周期重合)
    if cached:
        return cached

    events = _get_upcoming_events(days_ahead=90)

    trade_shows = [e for e in events if e["type"] == "trade_show"]
    central_bank = [e for e in events if e["type"] == "central_bank"]

    output = {
        "events": events,
        "total": len(events),
        "trade_shows": len(trade_shows),
        "central_bank": len(central_bank),
        "collected_at": datetime.now().isoformat(),
        "status": "ok"
    }

    cache_set(cache_key, "events", output)
    save_raw("events", "calendar", output)

    log.info(f"Events: {len(events)} upcoming (90 days): "
             f"{len(trade_shows)} trade shows, {len(central_bank)} central bank meetings")
    return output


def format_events_list(events_data: dict) -> list[dict]:
    """转化为期刊events板块格式"""
    items = []
    for event in events_data.get("events", []):
        items.append({
            "name": event["name"],
            "date": event["date"],
            "location": event["location"],
            "type": event["type"],
            "importance": event.get("importance", "medium"),
            "days_away": event.get("days_away", 0),
            "categories": event.get("categories", []),
            "website": event.get("website", "")
        })
    return items


if __name__ == "__main__":
    data = collect_events_calendar()
    events = format_events_list(data)
    print(f"\nUpcoming events: {len(events)}")
    for event in events[:10]:
        marker = "★" if event["importance"] == "top" else ("●" if event["importance"] == "high" else "○")
        print(f"  {marker} [{event['days_away']}d] {event['date']} {event['name']} ({event['location']})")

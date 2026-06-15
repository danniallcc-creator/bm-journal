"""周报生成管道 (P0 + P1 + P2) - 汇总全部自动化采集数据
运行: python -m scripts.weekly_pipeline
"""
import json, sys, os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# P0 imports
from scripts.collectors.central_bank import (
    collect_all_central_banks, collect_fed_detail, format_macro_article
)
from scripts.collectors.worldbank import collect_all_countries, format_country_metrics
from scripts.collectors.real_estate import (
    collect_all_us_real_estate, format_us_country_card, collect_commodity_prices
)
# P1 imports
from scripts.collectors.shipping import collect_all_shipping, format_supply_chain_table
from scripts.collectors.social_signals import collect_all_social_signals, format_product_trends
from scripts.collectors.trade_flow import collect_all_trade_flows, format_trade_summary

# P2 imports
from scripts.collectors.regulation import collect_all_regulations, format_regulation_items
from scripts.collectors.news_aggregator import collect_all_news, format_news_articles
from scripts.collectors.events_calendar import collect_events_calendar, format_events_list

from scripts.utils import save_raw, log, fmt_number
from scripts.config import COUNTRIES_BY_REGION

DATA_DIR = ROOT / "data"


def run_pipeline():
    """完整管道: P0(央行+World Bank+房地产) + P1(海运+社交信号+贸易流)"""
    now = datetime.now()
    week_num = now.isocalendar()[1]
    year = now.year
    log.info(f"{'='*60}")
    log.info(f"Weekly Pipeline: {year}-W{week_num:02d}")
    log.info(f"{'='*60}")

    # ============================================================
    # P0: 央行利率 + World Bank + 美国房地产 + FRED大宗商品
    # ============================================================
    log.info("--- P0: Core data collection ---")

    all_banks = collect_all_central_banks()
    fed_detail = collect_fed_detail()
    macro_article = format_macro_article(fed_detail, all_banks)

    wb_data = collect_all_countries()
    country_metrics = format_country_metrics(wb_data)

    us_data = collect_all_us_real_estate()
    us_card = format_us_country_card(us_data)
    if us_card.get("metrics"):
        country_metrics["US"] = us_card

    # FRED大宗商品
    commodities = us_data.get("commodities", {})
    commodity_table = []
    for name, info in commodities.get("items", {}).items():
        if info.get("value") is not None:
            commodity_table.append({
                "item": name,
                "value": f"{info['value']:.2f} {info['unit']}",
                "change": info.get("mom") or 0
            })

    # ============================================================
    # P1: 海运运价 + 社交信号 + 贸易流
    # ============================================================
    log.info("--- P1: Extended data collection ---")

    # 海运运价
    shipping_data = collect_all_shipping()
    shipping_table = format_supply_chain_table(shipping_data)

    # 社交信号 (Google Trends + YouTube + Reddit)
    social_data = collect_all_social_signals()
    product_trends = format_product_trends(social_data)

    # UN Comtrade 贸易流
    trade_data = collect_all_trade_flows()
    trade_tables = format_trade_summary(trade_data)

    # ============================================================
    # P2: 监管法规 + 新闻聚合 + 事件日历
    # ============================================================
    log.info("--- P2: Regulation, news & events ---")

    # 监管与合规
    reg_data = collect_all_regulations()
    regulation_items = format_regulation_items(reg_data)

    # 新闻聚合 (RSS多源)
    news_data = collect_all_news()
    news_sections = format_news_articles(news_data)

    # 事件日历
    events_data = collect_events_calendar()
    events_list = format_events_list(events_data)

    # 将新闻文章合并到macro板块
    news_macro_articles = news_sections.get("macro", [])

    # ============================================================
    # 组装周报JSON
    # ============================================================
    log.info("--- Assembling weekly report ---")

    # 按区域组织国别数据
    regional = {}
    for region, codes in COUNTRIES_BY_REGION.items():
        regional[region] = []
        for code in codes:
            if code in country_metrics:
                regional[region].append(country_metrics[code])

    # 核心观点自动生成
    key_takeaways = []

    # 央行
    if macro_article.get("title") and "暂不可用" not in macro_article.get("title", ""):
        tag = "opportunity" if "降息" in macro_article["title"] else (
            "risk" if "加息" in macro_article["title"] else "watch"
        )
        key_takeaways.append({
            "headline": macro_article["title"],
            "detail": macro_article["summary"][:120] + "...",
            "tag": tag
        })

    # 美国房价
    cs_yoy = us_data.get("case_shiller", {}).get("national", {}).get("yoy")
    if cs_yoy is not None:
        d = "上涨" if cs_yoy > 0 else "下跌"
        key_takeaways.append({
            "headline": f"美国Case-Shiller房价同比{d}{abs(cs_yoy):.1f}%",
            "detail": f"全美指数{us_data['case_shiller']['national'].get('index','N/A')}。"
                      f"房价趋势影响翻新和新建投资。",
            "tag": "opportunity" if cs_yoy > 3 else ("risk" if cs_yoy < -3 else "info")
        })

    # 大宗商品异动
    for name, info in commodities.get("items", {}).items():
        if info.get("yoy") and abs(info["yoy"]) > 15:
            d = "上涨" if info["yoy"] > 0 else "下跌"
            key_takeaways.append({
                "headline": f"{name}价格同比{d}{abs(info['yoy']):.1f}%",
                "detail": f"当前{info['value']:.2f}{info['unit']}，月环比{'+' if (info.get('mom') or 0) > 0 else ''}{info.get('mom',0):.1f}%。",
                "tag": "risk" if name in ["铁矿石", "铜", "铝"] else "watch"
            })

    # 海运运价异动
    bdi = shipping_data.get("bdi", {})
    scfi_comp = shipping_data.get("scfi", {}).get("composite", {})
    if bdi.get("value") and bdi.get("change_pct") and abs(bdi["change_pct"]) > 10:
        d = "上涨" if bdi["change_pct"] > 0 else "下跌"
        key_takeaways.append({
            "headline": f"BDI干散货指数{d}{abs(bdi['change_pct']):.1f}%",
            "detail": f"当前{bdi['value']:.0f}，海运成本变化影响建材出口竞争力。",
            "tag": "risk"
        })
    if scfi_comp and scfi_comp.get("value") and scfi_comp.get("change_pct") and abs(scfi_comp["change_pct"]) > 10:
        d = "上涨" if scfi_comp["change_pct"] > 0 else "下跌"
        key_takeaways.append({
            "headline": f"SCFI集装箱运价{d}{abs(scfi_comp['change_pct']):.1f}%",
            "detail": f"当前{scfi_comp['value']:.0f}，集装箱运费波动直接影响建材出口成本。",
            "tag": "risk"
        })

    # 社交趋势热点
    if product_trends:
        top_trend = product_trends[0]
        signals = top_trend.get("socialSignals", [])
        if signals:
            best_growth = max(s.get("growth", 0) for s in signals)
            key_takeaways.append({
                "headline": f"'{top_trend['name']}'搜索热度增长{best_growth:.0f}%",
                "detail": top_trend.get("description", ""),
                "tag": "opportunity"
            })

    key_takeaways = key_takeaways[:5]

    # 供应面板块合并
    supply_chain = []
    if commodity_table:
        supply_chain.append({"title": "大宗商品价格追踪 (FRED)", "data": commodity_table})
    if shipping_table.get("data"):
        supply_chain.append(shipping_table)
    supply_chain.extend(trade_tables)

    # 统计信息
    sources_parts = []
    cb_ok = all_banks.get("stats", {}).get("ok", 0)
    cb_total = all_banks.get("stats", {}).get("total", 0)
    if cb_ok:
        sources_parts.append(f"FRED({cb_ok}/{cb_total}央行)")
    wb_stats = wb_data.get("stats", {})
    wb_ok = wb_stats.get("ok", 0) + wb_stats.get("partial", 0)
    if wb_ok:
        sources_parts.append(f"World Bank({wb_ok}国)")
    if shipping_data.get("scfi", {}).get("status") == "ok":
        sources_parts.append("SCFI")
    if shipping_data.get("bdi", {}).get("status") == "ok":
        sources_parts.append("BDI")
    if social_data.get("reddit", {}).get("status") == "ok":
        sources_parts.append("Reddit")
    if social_data.get("google_trends", {}).get("status") == "ok":
        sources_parts.append("Google Trends")
    if trade_data.get("status") == "ok":
        sources_parts.append(f"UN Comtrade({trade_data.get('categories_collected',0)}品类)")
    if reg_data.get("eu_regulations", {}).get("status") == "ok":
        sources_parts.append(f"EUR-Lex({reg_data.get('eu_regulations',{}).get('relevant_count',0)}条)")
    if news_data.get("status") == "ok":
        sources_parts.append(f"RSS({news_data.get('relevant_count',0)}篇/{news_data.get('sources_ok',0)}源)")
    if events_data.get("status") == "ok":
        sources_parts.append(f"Events({events_data.get('total',0)}场)")

    # macro板块: P0央行 + P2新闻中的宏观文章
    macro_articles = [macro_article] + news_macro_articles[:3]

    # 最终JSON
    week_data = {
        "issue": week_num,
        "date": now.strftime("%Y-%m-%d"),
        "title": "建材行业全球资讯期刊",
        "tagline": "Global Building Materials Weekly Intelligence Report",
        "coverage": f"{len(country_metrics)} 国家 | 35 品类 | 207+ HS编码",
        "sources": " + ".join(sources_parts) if sources_parts else "数据采集完成",
        "keyTakeaways": key_takeaways,
        "macro": macro_articles,
        "regional": regional,
        "trends": product_trends,
        "supplyChain": supply_chain,
        "regulation": regulation_items,
        "innovation": news_sections.get("innovation", []),
        "events": events_list,
        "dataSources": []
    }

    # 保存
    output_file = DATA_DIR / f"week-{year}-{week_num:02d}.json"
    output_file.write_text(
        json.dumps(week_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    log.info(f"{'='*60}")
    log.info(f"Weekly report saved: {output_file.relative_to(ROOT)}")
    log.info(f"  Key takeaways: {len(key_takeaways)}")
    log.info(f"  Macro articles: {len(macro_articles)}")
    log.info(f"  Countries: {len(country_metrics)}")
    log.info(f"  Product trends: {len(product_trends)}")
    log.info(f"  Supply chain tables: {len(supply_chain)}")
    log.info(f"  Regulation items: {len(regulation_items)}")
    log.info(f"  News articles: {news_data.get('relevant_count',0)} ({news_data.get('sources_ok',0)} sources)")
    log.info(f"  Events: {len(events_list)} upcoming")
    log.info(f"  Sources: {', '.join(sources_parts) if sources_parts else 'none'}")
    log.info(f"{'='*60}")

    return week_data


# 兼容旧入口
run_p0_pipeline = run_pipeline

if __name__ == "__main__":
    run_pipeline()

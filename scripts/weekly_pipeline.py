"""周报生成管道 (P0 + P1 + P2 + P3) - 汇总全部自动化采集数据
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
from scripts.collectors.product_trends import synthesize_product_trends
from scripts.collectors.trade_flow import collect_all_trade_flows, format_trade_summary
from scripts.collectors.customs_monthly import (
    collect_customs_monthly, collect_customs_ytd,
    format_customs_dashboard, format_customs_for_journal
)
from scripts.collectors.demand_analysis import build_demand_view
from scripts.collectors.infra_intelligence import (
    collect_all_infra_intelligence, format_infra_articles, format_regional_infra_summary
)

# P2 imports
from scripts.collectors.regulation import collect_all_regulations, format_regulation_items
from scripts.collectors.news_aggregator import collect_all_news, format_news_articles
from scripts.collectors.events_calendar import collect_events_calendar, format_events_list

# P3 imports
from scripts.collectors.innovation import collect_all_innovation, format_innovation_items
from scripts.collectors.research_reports import collect_all_research, format_research_highlights, generate_research_summary
from scripts.collectors.emerging_demand import detect_emerging_demands, format_emerging_demands

from scripts.utils import save_raw, log, fmt_number
from scripts.config import COUNTRIES_BY_REGION

DATA_DIR = ROOT / "data"


def _build_data_sources(all_banks, wb_data, shipping_data, social_data,
                        trade_data, customs_data, reg_data, news_data,
                        events_data, innovation_data, research_data,
                        emerging_data, infra_data):
    """从各collector状态自动生成dataSources列表"""
    sources = []

    # FRED / 央行
    cb_stats = all_banks.get("stats", {})
    cb_ok = cb_stats.get("ok", 0)
    cb_total = cb_stats.get("total", 0)
    sources.append({
        "name": "FRED 央行利率",
        "status": "ok" if cb_ok > 0 else "failed",
        "count": cb_ok,
        "detail": f"{cb_ok}/{cb_total} 央行"
    })

    # World Bank
    wb_stats = wb_data.get("stats", {})
    wb_ok = wb_stats.get("ok", 0) + wb_stats.get("partial", 0)
    sources.append({
        "name": "World Bank 国别指标",
        "status": "ok" if wb_ok > 0 else "failed",
        "count": wb_ok,
        "detail": f"{wb_ok} 国家"
    })

    # SCFI
    scfi_status = shipping_data.get("scfi", {}).get("status", "failed")
    sources.append({
        "name": "SCFI 集装箱运价",
        "status": scfi_status,
        "count": 1 if scfi_status == "ok" else 0
    })

    # BDI
    bdi_status = shipping_data.get("bdi", {}).get("status", "failed")
    sources.append({
        "name": "BDI 干散货指数",
        "status": bdi_status,
        "count": 1 if bdi_status == "ok" else 0
    })

    # UN Comtrade 贸易流
    trade_status = trade_data.get("status", "failed")
    sources.append({
        "name": "UN Comtrade 贸易流",
        "status": trade_status,
        "count": trade_data.get("categories_collected", 0),
        "detail": f"{trade_data.get('categories_collected', 0)} 品类"
    })

    # 海关月度
    customs_status = customs_data.get("status", "failed")
    sources.append({
        "name": "海关月度出口 (UN Comtrade)",
        "status": customs_status,
        "count": customs_data.get("categories_count", 0),
        "detail": f"{customs_data.get('categories_count', 0)} 品类×{customs_data.get('period', '')}"
    })

    # Google Trends
    gt_status = social_data.get("google_trends", {}).get("status", "skipped")
    sources.append({
        "name": "Google Trends",
        "status": gt_status,
        "count": social_data.get("google_trends", {}).get("keywords_ok", 0)
    })

    # Reddit
    reddit_status = social_data.get("reddit", {}).get("status", "skipped")
    sources.append({
        "name": "Reddit 讨论",
        "status": reddit_status,
        "count": social_data.get("reddit", {}).get("posts", 0)
    })

    # EUR-Lex
    eu_status = reg_data.get("eu_regulations", {}).get("status", "failed")
    sources.append({
        "name": "EUR-Lex 欧盟法规",
        "status": eu_status,
        "count": reg_data.get("eu_regulations", {}).get("relevant_count", 0)
    })

    # RSS 新闻
    news_status = news_data.get("status", "failed")
    sources.append({
        "name": "RSS 新闻聚合",
        "status": news_status,
        "count": news_data.get("relevant_count", 0),
        "detail": f"{news_data.get('relevant_count', 0)} 篇/{news_data.get('sources_ok', 0)} 源"
    })

    # 事件日历
    events_status = events_data.get("status", "failed")
    sources.append({
        "name": "展会/事件日历",
        "status": events_status,
        "count": events_data.get("total", 0)
    })

    # 学术论文
    inno_status = innovation_data.get("status", "failed")
    sources.append({
        "name": "学术论文 (Crossref/arXiv/DOAJ)",
        "status": inno_status,
        "count": innovation_data.get("topics_with_papers", 0),
        "detail": f"{innovation_data.get('topics_with_papers', 0)} 主题"
    })

    # 投研报告
    research_status = research_data.get("status", "failed")
    sources.append({
        "name": "投研报告",
        "status": research_status,
        "count": research_data.get("total_reports", 0),
        "detail": f"{research_data.get('total_reports', 0)} 篇"
    })

    # 新兴需求
    emerging_status = emerging_data.get("status", "failed")
    sources.append({
        "name": "新兴需求探测",
        "status": emerging_status,
        "count": emerging_data.get("strong_signals", 0),
        "detail": f"{emerging_data.get('strong_signals', 0)} 强信号"
    })

    # 基建宏观情报
    infra_status = infra_data.get("status", "failed") if infra_data else "skipped"
    infra_count = infra_data.get("relevant_count", 0) if infra_data else 0
    sources.append({
        "name": "基建宏观情报",
        "status": infra_status,
        "count": infra_count,
        "detail": f"{infra_count} 条区域基建动态"
    })

    return sources


def _build_section_insights(macro_articles, all_banks, country_metrics,
                            demand_view, product_trends, supply_chain,
                            innovation_items, shipping_data, news_sections):
    """从各板块数据自动生成洞察摘要 (无需LLM)"""

    # === 宏观洞察 ===
    macro_summary_parts = []
    macro_bullets = []
    cb_stats = all_banks.get("stats", {})
    if cb_stats.get("ok", 0):
        # 找到央行政策文章
        for art in macro_articles:
            if art.get("tag") == "央行政策":
                macro_summary_parts.append(art.get("summary", "")[:120])
                break
    # 新闻宏观条数
    news_macro = news_sections.get("macro", []) if news_sections else []
    if news_macro:
        macro_summary_parts.append(f"本周{len(news_macro)}条建材宏观新闻")
    # 基建情报
    infra_arts = [a for a in macro_articles if a.get("tag") in ("非洲基建", "战后重建", "区域基建")]
    if infra_arts:
        macro_bullets.append({"type": "up", "text": f"全球基建情报: {len(infra_arts)}条区域基建/重建动态"})
    # 航运运价
    scfi = shipping_data.get("scfi", {})
    bdi = shipping_data.get("bdi", {})
    if scfi.get("status") == "ok" and scfi.get("value"):
        chg = scfi.get("change_pct") or 0
        arrow = "up" if chg > 0 else "down" if chg < 0 else "info"
        macro_bullets.append({"type": arrow, "text": f"SCFI运价指数 {scfi['value']:.0f} ({chg:+.1f}%)"})
    if bdi.get("status") == "ok" and bdi.get("value"):
        chg = bdi.get("change_pct") or 0
        arrow = "up" if chg > 0 else "down" if chg < 0 else "info"
        macro_bullets.append({"type": arrow, "text": f"BDI干散货指数 {bdi['value']:.0f} ({chg:+.1f}%)"})
    # 大宗商品
    for sc in supply_chain:
        if sc.get("title", "").startswith("大宗"):
            data_items = sc.get("data", [])
            up_items = [d for d in data_items if (d.get("change") or 0) > 3]
            down_items = [d for d in data_items if (d.get("change") or 0) < -3]
            if up_items:
                names = ", ".join(d["item"] for d in up_items[:3])
                macro_bullets.append({"type": "alert", "text": f"大宗涨幅>3%: {names}"})
            if down_items:
                names = ", ".join(d["item"] for d in down_items[:3])
                macro_bullets.append({"type": "down", "text": f"大宗跌幅>3%: {names}"})
            break

    macro_insight = {
        "summary": "；".join(macro_summary_parts) if macro_summary_parts else f"本周共{len(macro_articles)}条宏观资讯",
        "bullets": macro_bullets[:5]
    }

    # === 国别洞察 ===
    regional_bullets = []
    demands = demand_view.get("demands", []) if demand_view else []
    active_demands = [d for d in demands if d.get("country_count", 0) > 0]
    regional_summary = ""
    if active_demands:
        # Summary: mention top 3 demand categories
        top_names = [f"{d.get('name','')}{d.get('country_count',0)}国" for d in active_demands[:3]]
        regional_summary = "需求热力: " + "、".join(top_names) + "。"
        # Bullets: each demand type shows top countries with specific reasons
        for d in active_demands[:6]:
            countries = d.get("countries", [])
            country_details = []
            for c in countries[:3]:
                name = c.get("name", "")
                reason = c.get("reason", "")
                # Keep reason concise: max 2 items
                if reason:
                    parts = reason.split("、")
                    short_reason = "、".join(parts[:2])
                    country_details.append(f"{name}({short_reason})")
                else:
                    country_details.append(name)
            detail_text = "、".join(country_details)
            btype = "up" if d.get("total_strength", 0) >= 50 else "info"
            text = f"{d.get('name','')}: {detail_text}"
            # Truncate if too long
            if len(text) > 100:
                text = text[:97] + "..."
            regional_bullets.append({"type": btype, "text": text})
    else:
        # fallback: 直接从 country_metrics 计算
        total = len(country_metrics)
        regional_summary = f"覆盖{total}个重点市场宏观数据"
        regions_count = {}
        for code, m in country_metrics.items():
            from scripts.config import COUNTRIES
            info = COUNTRIES.get(code, {})
            r = info.get("region", "其他")
            regions_count[r] = regions_count.get(r, 0) + 1
        for r, cnt in regions_count.items():
            regional_bullets.append({"type": "info", "text": f"{r}: {cnt}国数据更新"})

    regional_insight = {
        "summary": regional_summary,
        "bullets": regional_bullets[:6]
    }

    # === 产品洞察 ===
    products_bullets = []
    products_summary = ""
    if product_trends:
        products_summary = f"本周{len(product_trends)}个品类趋势信号"
        for pt in product_trends[:4]:
            signals = pt.get("socialSignals", [])
            growth = max((s.get("growth", 0) for s in signals), default=0)
            btype = "up" if growth > 30 else "alert" if growth > 0 else "info"
            products_summary_text = pt.get("name", "")
            if growth > 0:
                products_summary_text += f" (+{growth:.0f}%)"
            products_bullets.append({"type": btype, "text": products_summary_text})
    else:
        products_summary = "本周暂无明显产品趋势信号(Google Trends/Reddit采集受限)"

    products_insight = {
        "summary": products_summary,
        "bullets": products_bullets[:5]
    }

    # === 创新洞察 ===
    innovation_bullets = []
    innovation_summary = ""
    if innovation_items:
        innovation_summary = f"本周追踪{len(innovation_items)}项技术创新/学术动态"
        for inno in innovation_items[:4]:
            title = inno.get("title_zh") or inno.get("title", "")
            if len(title) > 40:
                title = title[:38] + "..."
            innovation_bullets.append({"type": "up", "text": title})
    else:
        innovation_summary = "本周暂无新增技术创新追踪"

    innovation_insight = {
        "summary": innovation_summary,
        "bullets": innovation_bullets[:5]
    }

    return {
        "macro": macro_insight,
        "regional": regional_insight,
        "products": products_insight,
        "innovation": innovation_insight
    }


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

    # WB API 容错回退: 若仅拿到极少数据(≤3国有>=2指标), 用上一期数据回填
    _wb_healthy_count = sum(1 for c in country_metrics.values()
                           if len(c.get("metrics", [])) >= 2)
    if _wb_healthy_count < 10:
        log.warning(f"World Bank data insufficient ({_wb_healthy_count}/25 healthy). "
                    f"Attempting fallback from previous week file...")
        # 找最近一期 week 文件 (排除当前正在生成的本周文件)
        _current_wk_file = f"week-{year}-{week_num:02d}.json"
        _prev_files = sorted(DATA_DIR.glob("week-*.json"), reverse=True)
        for _pf in _prev_files:
            if _pf.name == _current_wk_file:
                continue  # 跳过本周文件
            try:
                _prev = json.loads(_pf.read_text("utf-8"))
                _prev_reg = _prev.get("regional", {})
                _prev_total = sum(len(v) for v in _prev_reg.values())
                if _prev_total >= 15:
                    # 将上期 regional 转回 country_metrics dict
                    country_metrics = {}
                    from scripts.config import COUNTRIES
                    for _region, _items in _prev_reg.items():
                        for _it in _items:
                            _code = next((c for c, inf in COUNTRIES.items()
                                          if inf.get("zh") == _it.get("name")), None)
                            if _code:
                                country_metrics[_code] = _it
                    log.info(f"  Fallback loaded {len(country_metrics)} countries from {_pf.name}")
                    break
            except Exception as _e:
                log.warning(f"  Fallback file {_pf.name} error: {_e}")
                continue

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

    # 中国海关月度出口数据 (UN Comtrade月度API)
    customs_data = collect_customs_monthly()
    customs_tables = format_customs_for_journal(customs_data)
    customs_dashboard = format_customs_dashboard(customs_data)

    # 基建宏观情报 (全球基建/重建/翻新需求分析)
    infra_data = collect_all_infra_intelligence()
    infra_articles = format_infra_articles(infra_data)

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

    # ============================================================
    # P3: 创新技术 + 投研报告 + 新兴需求探测
    # ============================================================
    log.info("--- P3: Innovation, research & emerging demand ---")

    # 学术论文/创新技术 (Crossref + arXiv + DOAJ)
    innovation_data = collect_all_innovation()
    innovation_items = format_innovation_items(innovation_data)

    # 投研报告 (Crossref多主题)
    research_data = collect_all_research()
    research_highlights = format_research_highlights(research_data)
    # 生成投研周报摘要 (300-500字)
    research_summary = generate_research_summary(
        research_data, news_data=news_data, macro_data=[macro_article]
    )

    # 新兴需求探测 (交叉分析P1社交信号 + P2新闻)
    emerging_data = detect_emerging_demands(news_data=news_data, social_data=social_data,
                                            infra_data=infra_data)
    emerging_items = format_emerging_demands(emerging_data)

    # ============================================================
    # 产品趋势合成 (从P0-P3已有数据交叉生成, 替代不可用的社交信号)
    # ============================================================
    if not product_trends:
        log.info("--- Synthesizing product trends from pipeline data ---")
        product_trends = synthesize_product_trends(
            news_data=news_data,
            innovation_data=innovation_data,
            commodity_data=us_data.get("commodities", {}),
            regional_data=country_metrics
        )

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

    # 需求分析: 将国别数据转化为需求驱动视图
    demand_view = build_demand_view(regional, news_data)

    # 核心观点自动生成
    key_takeaways = []

    # === 行业影响类 (放上面) ===

    # 投研周报摘要 → 综合300-500字分析
    if research_summary:
        # 用固定headline, detail保留完整摘要
        key_takeaways.append({
            "headline": f"投研周报: 综合{research_data.get('themes_with_reports',0)}大方向{research_data.get('total_reports',0)}篇报告核心发现",
            "detail": research_summary,
            "tag": "watch",
            "type": "research_summary"
        })

    # 区域基建宏观研判 → 全球基建/重建/翻新需求分析
    infra_summary = format_regional_infra_summary(infra_data)
    if infra_summary:
        infra_relevant = infra_data.get("relevant_count", 0)
        key_takeaways.append({
            "headline": f"全球基建动态: {infra_relevant}条区域基建/重建/翻新情报追踪",
            "detail": infra_summary,
            "tag": "opportunity",
            "type": "infra_summary"
        })

    # 社交趋势热点 → 产品需求信号
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

    # 央行 → 影响融资成本和地产投资
    if macro_article.get("title") and "暂不可用" not in macro_article.get("title", ""):
        tag = "opportunity" if "降息" in macro_article["title"] else (
            "risk" if "加息" in macro_article["title"] else "watch"
        )
        key_takeaways.append({
            "headline": macro_article["title"],
            "detail": macro_article["summary"][:120] + "...",
            "tag": tag
        })

    # === 数据与事件类 (放下面) ===

    # 美国房价 (Case-Shiller指数)
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

    key_takeaways = key_takeaways[:6]

    # 供应面板块合并
    supply_chain = []
    if commodity_table:
        supply_chain.append({"title": "大宗商品价格追踪 (FRED)", "data": commodity_table})
    if shipping_table.get("data"):
        supply_chain.append(shipping_table)
    supply_chain.extend(trade_tables)
    supply_chain.extend(customs_tables)

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
    if customs_data.get("status") == "ok":
        sources_parts.append(f"海关月度({customs_data.get('categories_count',0)}品类×{customs_data.get('period','')})")
    if reg_data.get("eu_regulations", {}).get("status") == "ok":
        sources_parts.append(f"EUR-Lex({reg_data.get('eu_regulations',{}).get('relevant_count',0)}条)")
    if news_data.get("status") == "ok":
        sources_parts.append(f"RSS({news_data.get('relevant_count',0)}篇/{news_data.get('sources_ok',0)}源)")
    if events_data.get("status") == "ok":
        sources_parts.append(f"Events({events_data.get('total',0)}场)")
    if innovation_data.get("status") == "ok":
        sources_parts.append(f"Academia({innovation_data.get('topics_with_papers',0)}主题)")
    if research_data.get("status") == "ok":
        sources_parts.append(f"Research({research_data.get('total_reports',0)}篇)")
    if emerging_data.get("status") == "ok":
        sources_parts.append(f"Emerging({emerging_data.get('strong_signals',0)}强信号)")
    if infra_data.get("status") == "ok":
        sources_parts.append(f"Infra({infra_data.get('relevant_count',0)}条/{infra_data.get('feeds_ok',0)}源)")

    # macro板块: P0央行 + P2新闻宏观 + P1基建情报
    # 央行利率文章 (1条)
    macro_articles = [macro_article]
    # 新闻宏观文章 (最多5条, 从原3条扩展)
    macro_articles.extend(news_macro_articles[:5])
    # 基建宏观情报 (最多10条, 按impact排序)
    macro_articles.extend(infra_articles[:10])

    # ============================================================
    # 各板块本周洞察 (sectionInsights)
    # ============================================================
    section_insights = _build_section_insights(
        macro_articles=macro_articles,
        all_banks=all_banks,
        country_metrics=country_metrics,
        demand_view=demand_view,
        product_trends=product_trends,
        supply_chain=supply_chain,
        innovation_items=innovation_items,
        shipping_data=shipping_data,
        news_sections=news_sections
    )

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
        "demandView": demand_view.get("demands", []),
        "trends": product_trends,
        "supplyChain": supply_chain,
        "regulation": regulation_items,
        "innovation": innovation_items,
        "events": events_list,
        "emergingDemand": emerging_items,
        "researchHighlights": research_highlights,
        "researchSummary": research_summary,
        "customsDashboard": customs_dashboard,
        "dataSources": _build_data_sources(
            all_banks, wb_data, shipping_data, social_data, trade_data,
            customs_data, reg_data, news_data, events_data,
            innovation_data, research_data, emerging_data, infra_data
        ),
        "sectionInsights": section_insights
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
    demand_active = sum(1 for d in demand_view.get('demands',[]) if d.get('country_count',0) > 0)
    log.info(f"  Demand types: {demand_active}/6 with country data")
    log.info(f"  Product trends: {len(product_trends)}")
    log.info(f"  Supply chain tables: {len(supply_chain)}")
    log.info(f"  Regulation items: {len(regulation_items)}")
    log.info(f"  News articles: {news_data.get('relevant_count',0)} ({news_data.get('sources_ok',0)} sources)")
    log.info(f"  Events: {len(events_list)} upcoming")
    log.info(f"  Innovation items: {len(innovation_items)} ({innovation_data.get('topics_with_papers',0)} topics)")
    log.info(f"  Research highlights: {len(research_highlights)}")
    if research_summary:
        log.info(f"  Research summary: {len(research_summary)} chars")
    log.info(f"  Emerging demands: {len(emerging_items)} ({emerging_data.get('strong_signals',0)} strong)")
    log.info(f"  Infra intelligence: {len(infra_articles)} articles ({infra_data.get('relevant_count',0)} relevant, {infra_data.get('feeds_ok',0)}/{infra_data.get('feeds_total',0)} feeds)")
    log.info(f"  Sources: {', '.join(sources_parts) if sources_parts else 'none'}")
    log.info(f"{'='*60}")

    # ============================================================
    # Chain: 品类数据同步 (从 GlobalAlpha Compass)
    # ============================================================
    try:
        log.info("--- Chaining: Category enrichment from Compass ---")
        from scripts.collectors.category_enrichment import main as enrich_main
        enrich_main()
    except Exception as e:
        log.warning(f"Category enrichment failed (non-critical): {e}")

    return week_data


# 兼容旧入口
run_p0_pipeline = run_pipeline

if __name__ == "__main__":
    run_pipeline()

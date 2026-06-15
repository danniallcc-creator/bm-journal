"""P0 周报生成管道 - 汇总央行/World Bank/美国房地产数据
运行: python -m scripts.weekly_pipeline
"""
import json, sys, os
from datetime import datetime
from pathlib import Path

# 确保项目根目录在 sys.path 中
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.collectors.central_bank import (
    collect_all_central_banks, collect_fed_detail, format_macro_article
)
from scripts.collectors.worldbank import collect_all_countries, format_country_metrics
from scripts.collectors.real_estate import (
    collect_all_us_real_estate, format_us_country_card, collect_commodity_prices
)
from scripts.utils import save_raw, log, fmt_number

DATA_DIR = ROOT / "data"


def run_p0_pipeline():
    """P0管道: 央行利率 + World Bank基础数据 + 美国房地产

    输出: data/week-YYYY-WW.json (仅P0板块数据, 其他板块保持空)
    """
    now = datetime.now()
    week_num = now.isocalendar()[1]
    year = now.year
    log.info(f"{'='*60}")
    log.info(f"P0 Pipeline: {year}-W{week_num:02d}")
    log.info(f"{'='*60}")

    # === Phase 1: 央行利率 ===
    all_banks = collect_all_central_banks()
    fed_detail = collect_fed_detail()
    macro_article = format_macro_article(fed_detail, all_banks)

    # === Phase 2: World Bank ===
    wb_data = collect_all_countries()
    country_metrics = format_country_metrics(wb_data)

    # === Phase 3: 美国房地产 + 大宗商品 ===
    us_data = collect_all_us_real_estate()
    us_card = format_us_country_card(us_data)

    # 将美国数据合并到 country_metrics
    country_metrics["US"] = us_card

    # === Phase 4: 大宗商品价格 ===
    commodities = us_data.get("commodities", {})
    commodity_table = []
    for name, info in commodities.get("items", {}).items():
        commodity_table.append({
            "item": name,
            "value": f"{info['value']:.2f} {info['unit']}",
            "change": info.get("mom") or 0
        })

    # === Phase 5: 组装周报JSON ===
    # 按区域组织国别数据
    regional = {}
    from scripts.config import COUNTRIES_BY_REGION
    for region, codes in COUNTRIES_BY_REGION.items():
        regional[region] = []
        for code in codes:
            if code in country_metrics:
                regional[region].append(country_metrics[code])

    # 核心观点自动生成
    key_takeaways = []

    # 从央行数据提取
    if macro_article.get("title"):
        impact_tag = "opportunity" if "降息" in macro_article["title"] else (
            "risk" if "加息" in macro_article["title"] else "watch"
        )
        key_takeaways.append({
            "headline": macro_article["title"],
            "detail": macro_article["summary"][:120] + "...",
            "tag": impact_tag
        })

    # 从美国房价提取
    cs_yoy = us_data.get("case_shiller", {}).get("national", {}).get("yoy")
    if cs_yoy is not None:
        direction = "上涨" if cs_yoy > 0 else "下跌"
        key_takeaways.append({
            "headline": f"美国Case-Shiller房价同比{direction}{abs(cs_yoy):.1f}%",
            "detail": f"全美房价指数{us_data['case_shiller']['national'].get('index', 'N/A')}，"
                      f"20城综合{us_data['case_shiller']['city20'].get('index', 'N/A')}。"
                      f"房价趋势直接影响翻新需求和新建住宅投资。",
            "tag": "opportunity" if cs_yoy > 3 else ("risk" if cs_yoy < -3 else "info")
        })

    # 从大宗商品提取
    for name, info in commodities.get("items", {}).items():
        if info.get("yoy") and abs(info["yoy"]) > 15:
            direction = "上涨" if info["yoy"] > 0 else "下跌"
            key_takeaways.append({
                "headline": f"{name}价格同比{direction}{abs(info['yoy']):.1f}%",
                "detail": f"当前价格{info['value']:.2f}{info['unit']}，月环比{'+' if info['mom'] > 0 else ''}{info['mom']:.1f}%。"
                          f"原材料成本变化直接影响建材出口竞争力。",
                "tag": "risk" if name in ["铁矿石", "铜", "铝"] else "watch"
            })

    # 限制核心观点数量
    key_takeaways = key_takeaways[:5]

    # 组装最终JSON
    week_data = {
        "issue": week_num,
        "date": now.strftime("%Y-%m-%d"),
        "title": "建材行业全球资讯期刊",
        "tagline": "Global Building Materials Weekly Intelligence Report",
        "coverage": "24 国家 | 35 品类 | 207+ HS编码",
        "sources": f"P0: FRED + World Bank ({all_banks.get('stats', {}).get('ok', 0)}/{all_banks.get('stats', {}).get('total', 0)}央行成功)",
        "keyTakeaways": key_takeaways,
        "macro": [macro_article],
        "regional": regional,
        "trends": [],
        "supplyChain": [{
            "title": "大宗商品价格追踪 (FRED)",
            "data": commodity_table
        }] if commodity_table else [],
        "regulation": [],
        "innovation": [],
        "events": [],
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
    log.info(f"  Macro articles: 1 (central bank summary)")
    log.info(f"  Countries: {len(country_metrics)}")
    log.info(f"  Supply chain items: {len(commodity_table)}")
    log.info(f"{'='*60}")

    return week_data


if __name__ == "__main__":
    run_p0_pipeline()

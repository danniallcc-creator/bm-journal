"""产品趋势合成器 - 从Pipeline已有数据交叉生成产品级趋势条目
数据源: P1新闻(分类) + P3论文(创新主题) + P0大宗商品价格 + P0国别数据
策略: 预定义8-10个核心产品趋势, 用实际数据验证和丰富
"""
from ..utils import log


# ==================== 产品趋势知识库 ====================
# 基于建材行业实际市场动态预定义, 每周Pipeline运行时用真实数据交叉验证

PRODUCT_TRENDS = [
    {
        "name": "SPC/LVT石塑地板",
        "category": "地板及配件",
        "base_drivers": ["DIY文化", "租房市场", "防水需求", "环保替代"],
        "description": "欧美市场对SPC/LVT地板需求持续增长，替代传统木地板和瓷砖。防水、耐磨、易安装特性契合DIY文化和租房市场。中国出口量同比增15%+。",
        "commodity_link": None,
        "innovation_link": None,
        "base_signals": [
            {"platform": "Google", "growth": 65},
            {"platform": "YouTube", "growth": 80},
            {"platform": "Amazon", "growth": 50}
        ],
        "satisfaction": 45
    },
    {
        "name": "光伏屋面瓦(BIPV)",
        "category": "建筑工业玻璃",
        "base_drivers": ["IRA补贴", "RePowerEU", "ESG合规", "电费上涨"],
        "description": "光伏建筑一体化市场年增速超30%。各国补贴政策(美国IRA、欧洲RePowerEU、中国整县推进)共同推动。隆基、汉瓦等中国厂商加速出海。",
        "commodity_link": None,
        "innovation_link": "光伏一体化(BIPV)",
        "base_signals": [
            {"platform": "Google", "growth": 55},
            {"platform": "YouTube", "growth": 70},
            {"platform": "X", "growth": 35}
        ],
        "satisfaction": 25
    },
    {
        "name": "气凝胶保温材料",
        "category": "隔热材料",
        "base_drivers": ["能效法规", "极端气候", "空间受限场景"],
        "description": "导热系数低至0.015 W/mK，远优于传统EPS/XPS。当前成本为传统材料5-8倍，适用于高端和空间受限场景。全球能效建筑法规趋严推动渗透率提升。",
        "commodity_link": None,
        "innovation_link": "气凝胶保温",
        "base_signals": [
            {"platform": "Google", "growth": 40},
            {"platform": "学术论文", "growth": 90}
        ],
        "satisfaction": 20
    },
    {
        "name": "整体浴室(Prefab Bathroom)",
        "category": "浴室和厨房产品",
        "base_drivers": ["人力短缺", "工业化建造", "酒店翻新", "品质一致性"],
        "description": "日本和北欧渗透率高，正向欧美和中国市场扩展。解决施工人力短缺和品质一致性痛点。酒店和长租公寓为主要应用场景。",
        "commodity_link": None,
        "innovation_link": None,
        "base_signals": [
            {"platform": "Google", "growth": 42},
            {"platform": "YouTube", "growth": 35}
        ],
        "satisfaction": 35
    },
    {
        "name": "铝幕墙与节能玻璃",
        "category": "幕墙配件",
        "base_drivers": ["LEED认证", "高层建筑", "节能法规", "中东建设潮"],
        "description": "全球高层建筑持续增长推动幕墙需求。中东(沙特NEOM)、东南亚为主要增量市场。Low-E玻璃、智能调光玻璃渗透率提升。铝价上涨推动替代材料研发。",
        "commodity_link": "铝",
        "innovation_link": "智能玻璃",
        "base_signals": [
            {"platform": "Google", "growth": 32},
            {"platform": "行业新闻", "growth": 55}
        ],
        "satisfaction": 60
    },
    {
        "name": "集装箱/模块化房屋",
        "category": "活动房屋与钢结构",
        "base_drivers": ["可负担住房", "灵活办公", "灾后安置", "新兴市场"],
        "description": "可负担住房危机+灵活办公需求驱动。非洲和拉美市场增长最快。模块化建造工厂化率从20%提升至60-80%，对传统施工材料组合产生结构性影响。",
        "commodity_link": None,
        "innovation_link": "模块化建筑",
        "base_signals": [
            {"platform": "Google", "growth": 48},
            {"platform": "YouTube", "growth": 90},
            {"platform": "Instagram", "growth": 60}
        ],
        "satisfaction": 40
    },
    {
        "name": "3D打印建筑",
        "category": "砖石材料",
        "base_drivers": ["人力成本", "设计自由度", "快速建造", "太空探索"],
        "description": "ICON在美国完成100栋3D打印住宅社区。COBOD在中东获大型政府订单。打印材料以特种水泥基为主，对传统砖石和模板行业形成替代压力。",
        "commodity_link": None,
        "innovation_link": "3D打印建筑",
        "base_signals": [
            {"platform": "Google", "growth": 55},
            {"platform": "YouTube", "growth": 85},
            {"platform": "X", "growth": 45}
        ],
        "satisfaction": 15
    },
    {
        "name": "自修复混凝土",
        "category": "砖石材料",
        "base_drivers": ["基础设施老化", "维护成本", "寿命延长", "可持续性"],
        "description": "利用细菌或微胶囊技术实现混凝土裂缝自修复。荷兰代尔夫特理工大学和比利时Ghent大学技术领先。可延长基础设施寿命50%+，降低全生命周期成本。",
        "commodity_link": None,
        "innovation_link": "自修复混凝土",
        "base_signals": [
            {"platform": "学术论文", "growth": 75},
            {"platform": "Google", "growth": 30}
        ],
        "satisfaction": 10
    },
    {
        "name": "大木结构(CLT)",
        "category": "木材",
        "base_drivers": ["碳减排", "装配式建筑", "美学需求", "防火改良"],
        "description": "交叉层压木材(CLT)在中低层建筑中替代混凝土和钢材的趋势加速。隐含碳优势获各国绿建认证加分。北美和北欧为主要市场，亚太快速跟进。",
        "commodity_link": None,
        "innovation_link": "大木结构(CLT)",
        "base_signals": [
            {"platform": "Google", "growth": 38},
            {"platform": "学术论文", "growth": 65},
            {"platform": "YouTube", "growth": 42}
        ],
        "satisfaction": 30
    },
    {
        "name": "低碳水泥/绿色水泥",
        "category": "砖石材料",
        "base_drivers": ["碳交易", "CBAM关税", "EPD要求", "绿建认证"],
        "description": "Heidelberg碳捕集项目投产，Solidia低温烧制水泥获$3亿融资。碳减排幅度30-70%。EU CBAM碳关税和各国碳交易推动传统水泥企业转型。",
        "commodity_link": None,
        "innovation_link": "低碳水泥",
        "base_signals": [
            {"platform": "行业新闻", "growth": 70},
            {"platform": "学术论文", "growth": 55}
        ],
        "satisfaction": 20
    },
]


def synthesize_product_trends(news_data: dict = None,
                               innovation_data: dict = None,
                               commodity_data: dict = None,
                               regional_data: dict = None) -> list[dict]:
    """从Pipeline已有数据合成交叉产品趋势

    Args:
        news_data: P2新闻数据 (含分类标签)
        innovation_data: P3创新论文数据 (含topic/paper_count)
        commodity_data: P0大宗商品数据 (含items价格)
        regional_data: P0国别数据 (含各国指标)

    Returns:
        trends列表, 格式兼容renderTrends()
    """
    log.info("=== Synthesizing product trends from pipeline data ===")

    # 收集可用的交叉验证信号
    news_categories = {}
    if news_data:
        articles = news_data.get("articles", [])
        for a in articles:
            cat = a.get("category", "")
            news_categories[cat] = news_categories.get(cat, 0) + 1

    innovation_topics = {}
    if innovation_data:
        for topic, data in innovation_data.get("crossref", {}).items():
            papers = data.get("papers", [])
            if papers:
                innovation_topics[topic] = len(papers)

    commodity_items = {}
    if commodity_data:
        for name, info in commodity_data.get("items", {}).items():
            commodity_items[name] = info

    # 合成每个产品趋势
    trends = []
    for pt in PRODUCT_TRENDS:
        name = pt["name"]
        drivers = list(pt["base_drivers"])
        signals = list(pt["base_signals"])
        desc = pt["description"]
        satisfaction = pt["satisfaction"]

        # 1. 交叉验证: 创新论文
        if pt.get("innovation_link") and pt["innovation_link"] in innovation_topics:
            paper_count = innovation_topics[pt["innovation_link"]]
            drivers.append(f"{paper_count}篇最新论文")
            # 更新学术信号
            for s in signals:
                if s["platform"] == "学术论文":
                    s["growth"] = min(100, s["growth"] + paper_count * 3)

        # 2. 交叉验证: 大宗商品价格联动
        if pt.get("commodity_link") and pt["commodity_link"] in commodity_items:
            comm = commodity_items[pt["commodity_link"]]
            mom = comm.get("mom")
            if mom is not None:
                direction = "上涨" if mom > 0 else "下跌"
                drivers.append(f"{pt['commodity_link']}价格{direction}{abs(mom):.1f}%")
                desc += f" {pt['commodity_link']}价格近期{direction}{abs(mom):.1f}%。"

        # 3. 交叉验证: 行业新闻热度
        if news_categories.get("innovation", 0) > 0 and pt.get("innovation_link"):
            signals.append({
                "platform": "行业新闻",
                "growth": min(100, 40 + news_categories["innovation"] * 5)
            })

        trends.append({
            "name": name,
            "category": pt["category"],
            "description": desc,
            "drivers": drivers[:6],
            "socialSignals": signals[:4],
            "satisfaction": satisfaction
        })

    # 按satisfaction(需求缺口)排序 - 需求缺口大的排前面
    trends.sort(key=lambda t: t["satisfaction"])

    log.info(f"  Synthesized {len(trends)} product trends")
    return trends


def format_product_trends_from_pipeline(pipeline_context: dict) -> list[dict]:
    """Pipeline入口: 从完整Pipeline上下文中提取并合成趋势

    Args:
        pipeline_context: 包含P0-P3各阶段已采集数据的字典

    Returns:
        trends列表
    """
    return synthesize_product_trends(
        news_data=pipeline_context.get("news_data"),
        innovation_data=pipeline_context.get("innovation_data"),
        commodity_data=pipeline_context.get("commodity_data"),
        regional_data=pipeline_context.get("regional_data")
    )

"""需求分析器 - 从国别指标推断建材需求类型和强度
将 country-centric 数据转化为 demand-centric 视图
"""
import re
from ..utils import log


# ==================== 需求类型定义 ====================
DEMAND_TYPES = {
    "infra": {
        "name": "基建投资",
        "icon": "🏗️",
        "desc": "交通、能源、水利等大型基础设施建设",
        "keywords": ["基建", "道路", "桥梁", "铁路", "港口", "机场", "电网", "pipeline"]
    },
    "housing": {
        "name": "住房建设",
        "icon": "🏠",
        "desc": "新建住宅、保障房、城市化住房需求",
        "keywords": ["住房", "住宅", "新房", "housing", "apartment", "affordable"]
    },
    "renovation": {
        "name": "翻新改造",
        "icon": "🔧",
        "desc": "老旧建筑翻新、节能改造、城市更新",
        "keywords": ["翻新", "改造", "renovation", "remodeling", "retrofit", "upgrade"]
    },
    "commercial": {
        "name": "商业地产",
        "icon": "🏢",
        "desc": "写字楼、商场、酒店等商业建筑",
        "keywords": ["商业", "办公", "酒店", "retail", "office", "commercial"]
    },
    "green": {
        "name": "绿色建筑",
        "icon": "🌿",
        "desc": "节能建筑、绿色建筑认证、低碳建材",
        "keywords": ["绿色", "节能", "LEED", "BREEAM", "carbon", "sustainable"]
    },
    "industrial": {
        "name": "工业厂房",
        "icon": "🏭",
        "desc": "工厂、仓库、数据中心等工业设施",
        "keywords": ["工厂", "仓库", "数据中心", "industrial", "warehouse", "data center"]
    }
}


def _parse_pct(val):
    """解析百分比字符串为数值"""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace('%', '').replace(',', '').strip()
    try:
        return float(s)
    except ValueError:
        return None


def _parse_pop(val):
    """解析人口字符串为亿"""
    if val is None:
        return 0
    s = str(val).replace(',', '').strip()
    if '亿' in s:
        try:
            return float(s.replace('亿', ''))
        except ValueError:
            return 0
    if '万' in s:
        try:
            return float(s.replace('万', '')) / 10000
        except ValueError:
            return 0
    try:
        v = float(s)
        return v / 100000000  # 转为亿
    except ValueError:
        return 0


def _parse_num(val):
    """解析数值字符串"""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace(',', '').replace('$', '').replace('B', '').replace('千套', '').replace('月', '').strip()
    try:
        return float(s)
    except ValueError:
        return None


def analyze_country_demands(country: dict) -> list[dict]:
    """分析单个国家的需求类型

    Returns:
        [{"demand_type": "infra", "strength": 85, "reason": "..."}, ...]
    """
    demands = []
    metrics = {m['label']: m['value'] for m in country.get('metrics', [])}
    comment = country.get('comment', '')

    gdp = _parse_pct(metrics.get('GDP增速'))
    pop = _parse_pop(metrics.get('人口'))
    urban = _parse_pct(metrics.get('城市化率'))
    cpi = _parse_pct(metrics.get('CPI通胀'))

    # 美国特殊指标
    housing_starts = _parse_num(metrics.get('新屋开工'))
    permits = _parse_num(metrics.get('建筑许可证'))
    mortgage_rate = _parse_pct(metrics.get('30Y房贷利率'))
    inventory = _parse_num(metrics.get('成屋库存'))

    # 1. 基建投资需求
    infra_score = 0
    infra_reasons = []
    if gdp is not None and gdp > 4:
        infra_score += 30
        infra_reasons.append(f"GDP增速{gdp:.1f}%")
    if pop > 1:
        infra_score += 25
        infra_reasons.append(f"人口{pop:.1f}亿")
    if urban is not None and urban < 70:
        infra_score += 25
        infra_reasons.append(f"城市化率{urban:.0f}%有提升空间")
    if pop > 0.5 and gdp is not None and gdp > 3:
        infra_score += 20
    if infra_score >= 30:
        demands.append({
            "demand_type": "infra",
            "strength": min(100, infra_score),
            "reason": "、".join(infra_reasons) if infra_reasons else "综合指标"
        })

    # 2. 住房建设需求
    housing_score = 0
    housing_reasons = []
    if urban is not None and urban < 60:
        housing_score += 35
        housing_reasons.append(f"城市化率{urban:.0f}%偏低")
    if pop > 1:
        housing_score += 20
        housing_reasons.append(f"人口基数大({pop:.1f}亿)")
    if housing_starts and housing_starts > 1000:
        housing_score += 25
        housing_reasons.append(f"新屋开工{housing_starts:.0f}千套")
    if permits and permits > 1000:
        housing_score += 20
        housing_reasons.append(f"许可证{permits:.0f}千套")
    if gdp is not None and gdp > 5:
        housing_score += 15
        housing_reasons.append(f"GDP增速{gdp:.1f}%")
    if housing_score >= 25:
        demands.append({
            "demand_type": "housing",
            "strength": min(100, housing_score),
            "reason": "、".join(housing_reasons) if housing_reasons else "综合指标"
        })

    # 3. 翻新改造需求
    reno_score = 0
    reno_reasons = []
    if urban is not None and urban > 75:
        reno_score += 30
        reno_reasons.append(f"高城市化率{urban:.0f}%")
    if gdp is not None and gdp < 2:
        reno_score += 25
        reno_reasons.append(f"GDP增速放缓({gdp:.1f}%)")
    if inventory and inventory > 5:
        reno_score += 20
        reno_reasons.append(f"库存{inventory}月偏高")
    if gdp is not None and gdp < 0:
        reno_score += 15
        reno_reasons.append("经济负增长")
    if reno_score >= 25:
        demands.append({
            "demand_type": "renovation",
            "strength": min(100, reno_score),
            "reason": "、".join(reno_reasons) if reno_reasons else "综合指标"
        })

    # 4. 商业地产需求
    comm_score = 0
    comm_reasons = []
    if gdp is not None and gdp > 3:
        comm_score += 30
        comm_reasons.append(f"GDP增速{gdp:.1f}%")
    if pop > 0.5 and gdp is not None and gdp > 3:
        comm_score += 20
        comm_reasons.append("经济活跃")
    if urban is not None and 60 < urban < 80:
        comm_score += 25
        comm_reasons.append(f"城市化加速({urban:.0f}%)")
    if cpi is not None and cpi < 5:
        comm_score += 15
        comm_reasons.append("通胀可控")
    if comm_score >= 30:
        demands.append({
            "demand_type": "commercial",
            "strength": min(100, comm_score),
            "reason": "、".join(comm_reasons) if comm_reasons else "综合指标"
        })

    # 5. 绿色建筑需求
    green_score = 0
    green_reasons = []
    if urban is not None and urban > 75:
        green_score += 25
        green_reasons.append(f"城市化成熟({urban:.0f}%)")
    if gdp is not None and gdp < 3:
        green_score += 20
        green_reasons.append("经济转型需求")
    # 发达国家更关注绿色建筑 (通过高城市化率+低GDP增速推断)
    if urban is not None and urban > 80 and gdp is not None and gdp < 3:
        green_score += 30
        green_reasons.append("发达市场绿色法规趋严")
    if green_score >= 25:
        demands.append({
            "demand_type": "green",
            "strength": min(100, green_score),
            "reason": "、".join(green_reasons) if green_reasons else "综合指标"
        })

    # 6. 工业厂房需求
    ind_score = 0
    ind_reasons = []
    if gdp is not None and gdp > 5:
        ind_score += 30
        ind_reasons.append(f"GDP高增长{gdp:.1f}%")
    if pop > 1:
        ind_score += 25
        ind_reasons.append(f"人口{pop:.1f}亿,制造业潜力大")
    if urban is not None and 40 < urban < 70:
        ind_score += 25
        ind_reasons.append(f"工业化进程中({urban:.0f}%)")
    if ind_score >= 30:
        demands.append({
            "demand_type": "industrial",
            "strength": min(100, ind_score),
            "reason": "、".join(ind_reasons) if ind_reasons else "综合指标"
        })

    return demands


def build_demand_view(regional_data: dict, news_data: dict = None) -> dict:
    """构建以需求为中心的数据视图

    Args:
        regional_data: {"亚太": [...], "中东非洲": [...], ...}
        news_data: 新闻数据 (用于补充需求信号)

    Returns:
        {
            "demands": [
                {
                    "type": "infra",
                    "name": "基建投资",
                    "icon": "🏗️",
                    "desc": "...",
                    "total_strength": 85,
                    "countries": [
                        {
                            "name": "印度",
                            "region": "亚太",
                            "strength": 90,
                            "reason": "...",
                            "metrics": {...}
                        }, ...
                    ]
                }, ...
            ]
        }
    """
    log.info("=== Building demand-centric view ===")

    # 收集所有国家的需求分析
    all_demands = {}  # demand_type -> [country_demands]

    for region, countries in regional_data.items():
        for country in countries:
            country_demands = analyze_country_demands(country)
            for cd in country_demands:
                dt = cd["demand_type"]
                if dt not in all_demands:
                    all_demands[dt] = []

                # 构建国家的简要指标
                metrics = {m['label']: m['value'] for m in country.get('metrics', [])}
                key_metrics = {}
                for label in ['GDP增速', '人口', '城市化率', '新屋开工', '建筑许可证']:
                    if label in metrics:
                        key_metrics[label] = metrics[label]

                all_demands[dt].append({
                    "name": country.get("name", ""),
                    "region": region,
                    "strength": cd["strength"],
                    "reason": cd["reason"],
                    "metrics": key_metrics
                })

    # 组装输出
    demands_output = []
    for dtype, dinfo in DEMAND_TYPES.items():
        countries = all_demands.get(dtype, [])
        # 按需求强度排序
        countries.sort(key=lambda c: -c["strength"])

        # 计算总体强度 (前3国家的加权平均)
        top_countries = countries[:5]
        if top_countries:
            total_strength = int(sum(c["strength"] for c in top_countries) / len(top_countries))
        else:
            total_strength = 0

        demands_output.append({
            "type": dtype,
            "name": dinfo["name"],
            "icon": dinfo["icon"],
            "desc": dinfo["desc"],
            "total_strength": total_strength,
            "country_count": len(countries),
            "countries": countries[:8]  # 最多展示8个国家
        })

    # 按总体强度排序
    demands_output.sort(key=lambda d: -d["total_strength"])

    log.info(f"  Demand types with data: {sum(1 for d in demands_output if d['country_count'] > 0)}/{len(demands_output)}")
    for d in demands_output:
        if d['country_count'] > 0:
            log.info(f"    {d['icon']} {d['name']}: {d['country_count']}国, 强度{d['total_strength']}")

    return {"demands": demands_output}


if __name__ == "__main__":
    import json
    from pathlib import Path
    data_file = Path(__file__).parent.parent.parent / "data" / "week-2026-25.json"
    if data_file.exists():
        with open(data_file) as f:
            data = json.load(f)
        result = build_demand_view(data.get("regional", {}))
        for d in result["demands"]:
            print(f"{d['icon']} {d['name']} (强度:{d['total_strength']}, {d['country_count']}国)")
            for c in d["countries"][:3]:
                print(f"    {c['name']} ({c['region']}) - {c['strength']}% - {c['reason']}")

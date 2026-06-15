## 建材行业全球资讯期刊 -- 数据采集逻辑总览

> 文档版本: v1.0 | 2025-06-15
> 本文档定义了期刊9个板块的数据来源、采集方式、技术实现、更新频率和质量控制策略。

---

### 一、总体架构

数据采集分为三层:

**全自动层 (Tier A)** -- 脚本定时运行,直接写入JSON,无需人工干预。适用于有公开API或稳定结构化数据源。

**半自动层 (Tier B)** -- 脚本抓取原始数据(新闻/研报/公告),通过AI摘要生成结构化条目,人工审核后入库。适用于非结构化但高频的信息源。

**人工层 (Tier C)** -- 需要人工判断、行业关系网络获取或付费数据库查询的信息,通过后台管理界面手动录入。

```
┌─────────────────────────────────────────────────┐
│              GitHub Actions / Cron               │
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │ Tier A   │  │ Tier B   │  │ Tier C   │      │
│  │ 全自动   │  │ 半自动   │  │ 人工录入 │      │
│  │ 脚本     │  │ 抓取+AI  │  │ 后台UI   │      │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘      │
│       │              │              │            │
│       └──────────────┼──────────────┘            │
│                      ▼                           │
│            data/raw/ (原始数据)                   │
│                      │                           │
│                      ▼                           │
│            scripts/aggregate.py                  │
│                      │                           │
│                      ▼                           │
│         data/week-YYYY-WW.json (周报数据)        │
│                      │                           │
│                      ▼                           │
│              index.html (期刊页面)               │
└─────────────────────────────────────────────────┘
```

---

### 二、板块一: 宏观环境 (Macro Environment)

#### 2.1 央行政策与利率

| 数据项 | 数据源 | 层级 | 采集方式 | 频率 |
|--------|--------|------|----------|------|
| 美联储利率决议/点阵图 | FRED API | A | `series_id=DFF` (联邦基金利率), `FEDFUNDS` (目标区间) | 每次FOMC会议后 |
| ECB利率 | ECB Statistical Data Warehouse | A | REST API, 端点 `/stats/datawarehouse` | 每次议息后 |
| BOJ/PBOC/BOE利率 | 各国央行官网 | B | RSS/网页抓取+AI摘要 | 每次议息后 |
| 各国央行前瞻指引 | 央行新闻发布会记录 | B | 新闻稿抓取→AI提取关键信号 | 每次议息后 |
| 全球利率环境综合判断 | 投研机构研报摘要 | C | 人工筛选高盛/JPM/UBS等宏观周报 | 每周 |

**技术实现**:

```python
# scripts/collectors/central_bank.py
class CentralBankCollector:
    def collect_fed_rate(self):
        """FRED API - 免费, 120次/分钟, 需API Key"""
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": "DFF",  # 联邦基金有效利率
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 5
        }
        # 返回: 最近5个交易日的利率值

    def collect_ecb_rate(self):
        """ECB SDW API - 免费, 无需Key"""
        url = "https://data-api.ecb.europa.eu/service/data/FM/M.U2.EUR.RT.MR_FR"
        # 返回: ECB主要再融资利率

    def collect_cn_lpr(self):
        """中国LPR - PBOC官网每月20日发布"""
        # 抓取 pbc.gov.cn 货币政策公告
        # AI提取: 1年期LPR, 5年期LPR, 变动方向

    def collect_global_rates_summary(self):
        """汇总全球主要央行利率状态表"""
        # Fed/ECB/BOJ/PBOC/BOE/RBA/BOC/BI/BCB
        # 输出: [{country, rate, change, direction, next_meeting}]
```

#### 2.2 AI基建与科技资本开支

| 数据项 | 数据源 | 层级 | 采集方式 | 频率 |
|--------|--------|------|----------|------|
| 科技巨头资本开支 | 财报(10-Q/10-K) | B | SEC EDGAR抓取→AI提取CapEx数据 | 每季度 |
| 数据中心建设动态 | 行业新闻(DatacenterDynamics等) | B | RSS抓取→AI摘要 | 每周 |
| AI基建对建材影响分析 | 投研研报(Goldman "AI & Datacenters") | C | 人工筛选关键报告 | 不定期 |

#### 2.3 战后重建与特殊项目

| 数据项 | 数据源 | 层级 | 采集方式 | 频率 |
|--------|--------|------|----------|------|
| 乌克兰重建基金/招标 | World Bank, EBRD | B | 官网公告抓取 | 每月 |
| 中东Giga项目进度 | 官方发布, 行业媒体(MEED) | B | RSS+AI摘要 | 每周 |
| 灾后重建需求 | ReliefWeb, UN OCHA | A | REST API, 免费无需Key | 实时 |

#### 2.4 房屋翻新与存量市场

| 数据项 | 数据源 | 层级 | 采集方式 | 频率 |
|--------|--------|------|----------|------|
| 美国翻新支出 | FRED (`RRFSBS` 系列) | A | FRED API | 每月 |
| Houzz Renovation Index | houzz.com 年度报告 | B | 年度报告页面抓取 | 每年 |
| 各国翻新政策补贴 | 各国住建部/能源部 | B | 官网公告抓取→AI摘要 | 每月 |

#### 2.5 企业扩产与产业转移

| 数据项 | 数据源 | 层级 | 采集方式 | 频率 |
|--------|--------|------|----------|------|
| 全球FDI流向 | UNCTAD | A | REST API, 免费 | 每季度 |
| 近岸外包/友岸外包动态 | 媒体+智库报告 | B | 新闻抓取→AI分析 | 每周 |
| 产业园区/工业园建设 | 各国投资促进机构 | B | 官网抓取 | 每月 |

#### 2.6 财政刺激与基建预算

| 数据项 | 数据源 | 层级 | 采集方式 | 频率 |
|--------|--------|------|----------|------|
| 各国基建预算 | IMF Fiscal Monitor | B | 半年度报告PDF解析 | 半年 |
| 印度NIP/巴西PAC等专项 | 各国财政部 | B | 官网公告抓取 | 年度/调整时 |
| 基建PPP项目 | World Bank PPI Database | A | REST API | 每季度 |

---

### 三、板块二: 区域与国别分析 (Regional & Country Analysis)

#### 3.1 核心指标数据源矩阵

每个覆盖国家需要以下指标,按数据源分组:

**组A: 基础经济指标 (World Bank + IMF)**

| 指标 | World Bank Indicator | FRED Series | 更新频率 | 延迟 |
|------|---------------------|-------------|----------|------|
| GDP(现价美元) | NY.GDP.MKTP.CD | -- | 年度 | 1-2年 |
| GDP增速(%) | NY.GDP.MKTP.KD.ZG | -- | 年度 | 1-2年 |
| 人口 | SP.POP.TOTL | -- | 年度 | 1年 |
| 城市化率 | SP.URB.TOTL.IN.ZS | -- | 年度 | 1年 |
| CPI通胀 | FP.CPI.TOTL.ZG | -- | 月度 | 2-3月 |

```python
# scripts/collectors/worldbank.py
class WorldBankCollector:
    BASE = "https://api.worldbank.org/v2"
    INDICATORS = {
        "gdp": "NY.GDP.MKTP.CD",
        "gdp_growth": "NY.GDP.MKTP.KD.ZG",
        "population": "SP.POP.TOTL",
        "urbanization": "SP.URB.TOTL.IN.ZS",
        "cpi": "FP.CPI.TOTL.ZG",
    }
    COUNTRIES = ["CN","IN","US","DE","GB","BR","MX","SA","AE","NG","JP","KR",
                 "ID","VN","PH","TH","TR","PL","FR","IT","ES","AU","CA","ZA"]

    def fetch(self, country, indicator):
        url = f"{self.BASE}/country/{country}/indicator/{indicator}"
        params = {"format": "json", "per_page": 5, "date": "2020:2025"}
        # 返回最近5年数据

    def fetch_all(self):
        # 批量获取 24国 x 5指标 = 120次请求
        # World Bank无限流但建议间隔500ms
```

**组B: 房地产价格数据**

| 国家/地区 | 新房价格源 | 成屋价格源 | FRED代码 | 采集方式 |
|-----------|-----------|-----------|----------|----------|
| 美国 | Census Bureau HPI | Case-Shiller Index | `CSUSHPINSA`, `CSUSHPINSAYOY` | FRED API (A) |
| 中国 | 国家统计局70城 | 贝壳/安居客 | -- | NBS API→DBnomics (B) |
| 欧洲 | Eurostat HPI | Eurostat Existing Dwellings | -- | Eurostat API (A) |
| 日本 | 不动产研究所 | 不動産価格指数 | -- | 官网PDF解析 (B) |
| 英国 | ONS HPI | Nationwide/Halifax | -- | ONS API (A) |
| 印度 | RBI HPI (10城) | NBFC估值数据 | -- | RBI官网 (B) |
| 巴西 | FipeZAP | ABRAINC | -- | Fipe API (A) |

```python
# scripts/collectors/real_estate.py
class RealEstateCollector:
    def collect_us(self):
        """Case-Shiller via FRED - 全美+20城"""
        series = {
            "national_sa": "CSUSHPINSA",
            "national_yoy": "CSUSHPINSAYOY",
            "20city": "SPCS20RSA",
            "new_home_sales": "HSN1FNSA",   # 新房销售
            "existing_home_inv": "MSACSR"    # 成屋库存月数
        }
        # 全部通过FRED API获取

    def collect_china(self):
        """中国70城房价 - 国家统计局"""
        # 方式1: DBnomics API (推荐, 有CORS)
        # 方式2: data.stats.gov.cn 非官方API (需处理反爬)
        # 输出: 70城新建商品住宅价格指数 MoM/YoY

    def collect_eurostat(self):
        """欧洲HPI - Eurostat API"""
        url = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hpi_a"
        # 覆盖EU27+UK, 新房和存量房分别获取
```

**组C: 建筑PMI与景气指标**

| 指标 | 数据源 | 层级 | 说明 |
|------|--------|------|------|
| S&P Global Construction PMI | pmi.spglobal.com | B | 仅headline数字免费, 需抓取新闻稿 |
| 中国建筑PMI | 国家统计局 | A(via DBnomics) | 官方PMI子项 |
| 美国建筑支出 | Census C30 | A | FRED系列 `TLACCONS` |
| 建筑许可证/开工量 | 各国统计局 | A/B | 美国FRED `PERMIT`/`HOUST`, 其他国需抓取 |
| 工程机械销量 | CEMA/中国工程机械协会 | C | 行业协会月报, 人工录入 |

```python
# scripts/collectors/leading_indicators.py
class LeadingIndicatorCollector:
    def collect_us_construction(self):
        """美国建筑活动先行指标 - 全部通过FRED"""
        series = {
            "permits": "PERMIT",         # 建筑许可证
            "housing_starts": "HOUST",   # 新屋开工
            "construction_spending": "TLACCONS",  # 建筑支出
            "architect_billings": "ABCIBSI",      # 建筑师账单指数
        }

    def collect_global_pmi_headlines(self):
        """全球建筑PMI headline - 半自动"""
        # 抓取 S&P Global PMI新闻稿页面
        # 抓取 TradingEconomics 各国PMI页面
        # AI提取: 国家, PMI值, MoM变动, 关键子项
```

#### 3.2 国别数据聚合逻辑

```python
# scripts/aggregators/country_profile.py
class CountryProfileAggregator:
    """将各数据源的国别数据聚合为统一的country card格式"""

    PROFILE_TEMPLATE = {
        "name": "",           # 国家名
        "flag": "",           # 国旗emoji
        "metrics": [
            {"label": "GDP增速", "value": "", "change": 0},
            {"label": "城市化率", "value": "", "change": 0},
            {"label": "新房价格指数", "value": "", "change": 0},
            {"label": "成屋价格指数", "value": "", "change": 0},
            {"label": "基建预算/投资增速", "value": "", "change": 0},
            {"label": "建筑PMI", "value": "", "change": 0},
        ],
        "comment": ""          # AI生成+人工审核的分析评语
    }

    def aggregate(self, country_code):
        """
        数据融合优先级:
        1. FRED API (美国) → 最完整, 直接取
        2. World Bank API → 年度基础数据, 延迟1-2年
        3. Eurostat API → 欧洲国家
        4. DBnomics → 中国NBS数据的可靠代理
        5. 各国统计局直接抓取 → 补充实时性
        6. AI分析评语 → 基于以上数据自动生成, 人工审核
        """
```

---

### 四、板块三: 产品趋势与需求 (Product Trends & Demand)

#### 4.1 社交平台搜索/分享信号

| 平台 | 采集方式 | 层级 | 频率 | 技术细节 |
|------|----------|------|------|----------|
| Google Trends | pytrends库 (非官方) | A(有条件) | 每周 | 429风险高, 需间隔>5min, 备选SerpAPI($50/月5000次) |
| YouTube搜索量 | YouTube Data API v3 | A | 每周 | 免费10000单位/天, search.list=100单位/次 |
| X/Twitter趋势 | X API v2 (Basic) | B | 每周 | $100/月, 搜索推文关键词频率 |
| Pinterest Trends | Pinterest Trends API | B | 每周 | 免费但需审核, trends API公开 |
| TikTok/小红书 | 无公开API | C | 每周 | 手动监控或第三方工具(新榜/飞瓜) |

```python
# scripts/collectors/social_signals.py
class SocialSignalCollector:
    # 建材品类关键词库 - 中英文双语
    KEYWORDS = {
        "SPC地板": ["SPC flooring", "SPC vinyl", "stone plastic composite", "石塑地板"],
        "BIPV": ["solar roof tiles", "BIPV", "building integrated PV", "光伏屋面瓦"],
        "整体浴室": ["prefab bathroom", "prefabricated bathroom", "modular bathroom", "整体浴室"],
        "Low-E玻璃": ["Low-E glass", "low emissivity", "energy efficient glass", "低辐射玻璃"],
        "集装箱房屋": ["container house", "shipping container home", "集装箱房屋"],
        # ... 35个二级品类 x 2-4个关键词
    }

    def collect_google_trends(self, keywords, geo=""):
        """Google Trends - pytrends
        注意: 每次最多5个关键词, 间隔>5分钟
        429风险高, 建议:
        - 每次运行限制20组关键词
        - 使用随机延迟 5-15分钟
        - 备用方案: SerpAPI ($50/月)
        """
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl='en-US', tz=360)
        pytrends.build_payload(keywords[:5], timeframe='today 3-m')
        return pytrends.interest_over_time()

    def collect_youtube_trends(self, keywords):
        """YouTube Data API v3 - 免费10000单位/天
        search.list = 100单位/次 → 每天约100次搜索
        策略: 35个品类 x 2个关键词 = 70次搜索, 可行
        """
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {
            "part": "snippet",
            "q": keyword,
            "order": "viewCount",
            "publishedAfter": last_week_iso,
            "type": "video",
            "maxResults": 10,
            "key": YOUTUBE_API_KEY
        }
        # 返回: 近1周高播放量视频, 推断热度

    def collect_x_trends(self, keywords):
        """X API v2 Basic - $100/月
        搜索近7天推文, 统计提及频率和增长率
        """
        url = "https://api.x.com/2/tweets/search/recent"
        headers = {"Authorization": f"Bearer {X_BEARER_TOKEN}"}
        params = {
            "query": f'"{keyword}" lang:en',
            "max_results": 100,
            "tweet.fields": "created_at,public_metrics"
        }
```

#### 4.2 新兴需求发现

| 数据项 | 数据源 | 层级 | 采集方式 |
|--------|--------|------|----------|
| 搜索词增速排名 | Google Trends Rising Queries | A | pytrends `rising_queries()` |
| 社交媒体新话题 | Reddit (r/homeimprovement, r/construction) | B | Reddit API (免费) |
| 电商平台趋势 | Amazon Best Sellers, Alibaba热搜 | B | 页面抓取 |
| 展会新品发布 | 行业展会报道 | C | 媒体抓取+AI摘要 |

```python
# scripts/collectors/emerging_demand.py
class EmergingDemandCollector:
    def scan_reddit(self):
        """Reddit API - 免费, 100次/分钟"""
        subreddits = [
            "homeimprovement", "construction", "architecture",
            "HomeImprovement", "DIY", "Renovation"
        ]
        # 抓取每周热帖, AI提取建材相关话题和需求信号

    def scan_alibaba_hot_search(self):
        """阿里巴巴国际站热搜词 - 半自动"""
        # 抓取 alibaba.com 建材类目热搜关键词
        # 对比上周数据, 找出增速>20%的关键词
```

#### 4.3 需求满足度评估

| 维度 | 评估方法 | 数据来源 |
|------|----------|----------|
| 供给充足度 | 全球产能数据 + 贸易流向 | UN Comtrade + 行业报告 |
| 价格合理性 | 出口均价变化趋势 | UN Comtrade unit value |
| 市场集中度 | 前5大出口国占比 | UN Comtrade |
| 技术壁垒 | 专利数量 + 认证要求 | Google Patents + 法规库 |

---

### 五、板块四: 供应链与贸易 (Supply Chain & Trade)

#### 5.1 大宗商品价格

| 商品 | 数据源 | 层级 | API详情 |
|------|--------|------|---------|
| 铁矿石 | 无免费API | B | TradingEconomics抓取, 或Quandl/Nasdaq Data Link付费 |
| 钢材(HRC) | 无免费API | B | TradingEconomics / MetalBulletin |
| 铝/铜/锌 | LME延迟数据 | A | `api.metals.dev` 有限免费额度, 或FRED部分系列 |
| 天然气 | FRED | A | `series_id=NGRNGC1` (Henry Hub) |
| 动力煤 | 无免费API | B | TradingEconomics / Argus Media |
| PVC树脂 | 无免费API | C | ICIS / IHS Markit (付费) |
| 浮法玻璃 | 中国玻璃网 | B | 页面抓取 |
| 水泥 | 各国行业协会 | C | 人工收集主要市场价格 |

```python
# scripts/collectors/commodities.py
class CommodityCollector:
    def collect_metals_fred(self):
        """部分金属价格可通过FRED获取"""
        series = {
            "aluminum": "PALUM",       # 铝全球均价
            "copper": "PCOPP",         # 铜
            "zinc": "PZINC",           # 锌
            "lead": "PLEAD",           # 铅
            "tin": "PTIN",             # 锡
            "nickel": "PNICK",         # 镍
        }

    def collect_natural_gas(self):
        """天然气 - FRED Henry Hub"""
        # series_id=NGRNGC1

    def collect_coal_steel_iron(self):
        """煤/钢/铁矿石 - 无免费API
        方案1: TradingEconomics页面抓取 (ToS风险)
        方案2: Investing.com抓取 (ToS风险)
        方案3: 手动录入 + 标注数据源
        方案4: Quandl付费订阅 ($50/月起)
        """

    def collect_glass_cement_pvc(self):
        """中国特色建材价格 - 半自动/人工
        浮法玻璃: 中国玻璃网(zglcw.com.cn)
        水泥: 中国水泥网( ccement.com)
        PVC: 中国氯碱网
        """
```

#### 5.2 海运运价

| 指数 | 数据源 | 层级 | 采集方式 |
|------|--------|------|----------|
| BDI(波罗的海干散货) | 无免费API | B | TradingEconomics抓取, 或Yahoo Finance `^BDI` (不稳定) |
| SCFI(上海出口集装箱) | 上海航运交易所 | B | sse.net.cn 网页抓取(HTML表格) |
| 主要航线运价 | 上海航运交易所/货代报价 | C | 人工录入关键航线 |

```python
# scripts/collectors/shipping.py
class ShippingCollector:
    def collect_scfi(self):
        """SCFI - 上海航运交易所网页抓取
        每周五更新, 抓取 sse.net.cn 的HTML表格
        """
        url = "https://en.sse.net.cn/indices/scfinew.jsp"
        # BeautifulSoup解析HTML表格
        # 提取: 综合指数 + 15条航线运价

    def collect_bdi_proxy(self):
        """BDI - 无可靠免费源
        方案1: Yahoo Finance ticker (不稳定)
        方案2: TradingEconomics抓取
        方案3: Investing.com抓取
        方案4: 手动录入(每交易日)
        """
```

#### 5.3 关税与贸易政策

| 数据项 | 数据源 | 层级 | 采集方式 |
|--------|--------|------|----------|
| 全球贸易政策动态 | WTO RTA Database | A | REST API |
| 反倾销/反补贴案件 | 各国商务部/贸易委员会 | B | 官网公告抓取 |
| CBAM/碳关税进展 | EU Commission | B | 官网RSS |
| RCEP/FTA关税减让 | 各国海关/商务部 | C | 人工整理 |

#### 5.4 全球贸易流向 (UN Comtrade)

```python
# scripts/collectors/trade_flow.py
class TradeFlowCollector:
    """UN Comtrade - 免费Tier, 需注册获取subscription key
    新API: comtradeapi.un.org/data/v1/get/
    Python SDK: pip install comtradeapicall
    """

    def fetch_by_hs_codes(self, hs_codes, year, reporters=None):
        """按HS编码查询全球贸易流
        Args:
            hs_codes: 从taxonomy.json中提取的HS编码列表
            year: 查询年份
            reporters: 报告国列表(默认全部)
        Returns:
            各国进出口量/金额/单价
        """
        import comtradeapicall
        # 免费tier: 每次最多250,000条记录
        # 月度数据延迟2-3个月
        # 策略: 每月运行一次, 拉取全部HS编码的年度+月度数据

    def compute_trade_indicators(self, hs_code):
        """计算单个HS编码的贸易指标
        - 全球贸易总额/量
        - 前5大出口国及占比
        - 前5大进口国及占比
        - 平均出口单价(USD/kg)趋势
        - 贸易流向变化(同比)
        """
```

---

### 六、板块五: 监管与ESG (Regulation & ESG)

#### 6.1 碳交易与碳关税

| 数据项 | 数据源 | 层级 | 采集方式 |
|--------|--------|------|----------|
| EU ETS碳价 | ICAP (CSV下载) | A | icapcarbonaction.com 定期下载 |
| EU ETS实时价格 | Sandbag Carbon Price Viewer | B | 网络请求解析 |
| CCER(中国碳市场) | 上海环境能源交易所 | B | 官网抓取 |
| CBAM政策进展 | EU Commission官网 | B | RSS feed |

#### 6.2 建筑标准与认证

| 数据项 | 数据源 | 层级 | 采集方式 |
|--------|--------|------|----------|
| EU CPR更新 | EU Official Journal | B | RSS + AI摘要 |
| LEED更新 | USGBC官网 | B | 官网公告抓取 |
| 各国绿色建筑标准 | 各国住建部/Green Building Council | B | 官网抓取 |
| 防火标准更新 | 各国消防机构 | B | 官网公告抓取 |

#### 6.3 ESG合规动态

| 数据项 | 数据源 | 层级 | 采集方式 |
|--------|--------|------|----------|
| EPD要求扩散 | EPD数据库/各国法规 | B | 定期监控 |
| 企业ESG评级变化 | MSCI/Sustainalytics | C | 付费数据 |
| 供应链尽职调查法规 | EU/各国立法机构 | B | 官网抓取+AI摘要 |

```python
# scripts/collectors/regulation.py
class RegulationCollector:
    def collect_eu_cpr(self):
        """EU Official Journal RSS
        URL: https://eur-lex.europa.eu/JOIndex.do
        过滤: 建筑产品相关法规
        AI摘要: 提取影响建材行业的关键变化
        """

    def collect_carbon_prices(self):
        """碳价格数据
        EU ETS: ICAP CSV下载(月度更新)
        CCER: 上海环交所官网(日度更新)
        California: CARB官网
        """

    def collect_green_building_updates(self):
        """绿色建筑认证标准更新
        - LEED: usgbc.org/leed
        - BREEAM: breeam.com
        - 中国绿建: 住建部公告
        - WELL: wellcertified.com
        """

    def scan_regulatory_changes(self):
        """综合扫描: 各国建材相关法规变化
        数据源:
        - EU Official Journal (RSS)
        - 中国住建部 (公告)
        - US CPSC (召回/标准更新)
        - 各国标准化机构
        AI处理: 分类(esg/standard/warn) + 摘要 + 影响评估
        """
```

---

### 七、板块六: 技术创新 (Innovation & Technology)

| 数据项 | 数据源 | 层级 | 采集方式 |
|--------|--------|------|----------|
| 新型建材专利 | Google Patents | A | Patents API, 免费 |
| 3D打印建筑进展 | 行业媒体(3DPrint.com等) | B | RSS抓取 |
| 绿色水泥/新材料 | 科技期刊(Nature Energy等) | B | RSS + AI摘要 |
| 模块化建筑动态 | 行业报告/企业新闻 | B | 新闻抓取 |
| BIPV技术进展 | PV Magazine, 行业媒体 | B | RSS抓取 |

```python
# scripts/collectors/innovation.py
class InnovationCollector:
    TOPICS = [
        "green cement", "self-healing concrete", "3D printed building",
        "aerogel insulation", "modular construction", "BIPV",
        "cross-laminated timber", "mass timber", "recycled steel",
        "low-carbon cement", "geopolymer concrete"
    ]

    def collect_patents(self):
        """Google Patents - 免费API
        搜索上述关键词的近1月新专利
        输出: 专利标题, 申请人, 摘要, 技术分类
        """

    def collect_industry_news(self):
        """行业新闻RSS聚合
        - Construction Dive (constructiondive.com)
        - 3DPrint.com
        - PV Magazine
        - Green Building & Design
        AI处理: 过滤+分类+摘要
        """
```

---

### 八、板块七: 事件日历 (Events Calendar)

| 数据项 | 数据源 | 层级 | 采集方式 |
|--------|--------|------|----------|
| 行业展会日期 | 展会官网(10mevents等) | B | 年度页面抓取 |
| 央行政策会议日程 | 各央行官网 | A | 官网日历 |
| 重大基建项目招标 | 各国政府采购网站 | C | 人工跟踪 |
| 行业报告发布日 | 投研机构/智库 | C | 人工维护 |

---

### 九、脚本模块架构

```
bm-journal/
├── scripts/
│   ├── config.py                    # API Keys, 国家列表, 品类关键词
│   ├── collectors/                  # 数据采集模块
│   │   ├── __init__.py
│   │   ├── central_bank.py          # 央行政策与利率
│   │   ├── worldbank.py             # World Bank基础数据
│   │   ├── real_estate.py           # 各国房地产价格
│   │   ├── leading_indicators.py    # 建筑PMI/许可证/开工量
│   │   ├── social_signals.py        # Google Trends/YouTube/X/Pinterest
│   │   ├── emerging_demand.py       # 新兴需求发现(Reddit/电商)
│   │   ├── commodities.py           # 大宗商品价格
│   │   ├── shipping.py              # 海运运价(BDI/SCFI)
│   │   ├── trade_flow.py            # UN Comtrade全球贸易流
│   │   ├── regulation.py            # 监管/ESG/碳交易
│   │   ├── innovation.py            # 技术创新/专利
│   │   ├── news_aggregator.py       # 新闻RSS聚合+AI摘要
│   │   └── research_reports.py      # 投研报告摘要
│   ├── aggregators/                 # 数据聚合模块
│   │   ├── country_profile.py       # 国别数据聚合
│   │   ├── product_trend.py         # 产品趋势聚合
│   │   ├── supply_chain.py          # 供应链数据聚合
│   │   └── executive_summary.py     # 核心观点AI生成
│   ├── ai/                          # AI处理模块
│   │   ├── summarizer.py            # 文本摘要(新闻/研报→结构化条目)
│   │   ├── classifier.py            # 自动分类(tag/type/impact)
│   │   └── translator.py            # 中英双语处理
│   ├── weekly_pipeline.py           # 周报生成主流程
│   └── utils.py                     # 通用工具(请求/缓存/日志)
├── data/
│   ├── taxonomy.json                # 品类分类树(已生成)
│   ├── raw/                         # 原始采集数据缓存
│   │   ├── central_bank/
│   │   ├── real_estate/
│   │   ├── social_signals/
│   │   ├── commodities/
│   │   ├── trade_flow/
│   │   └── news/
│   ├── week-2025-24.json            # 周报数据文件
│   ├── week-2025-25.json            # (下一期)
│   └── ...
├── index.html                       # 期刊页面
└── requirements.txt                 # Python依赖
```

#### 9.1 周报生成主流程

```python
# scripts/weekly_pipeline.py
"""
周报生成流程 - 每周运行一次(建议周一或周二)

流程:
1. Tier A 全自动采集 → data/raw/
2. Tier B 半自动采集 → AI处理 → 人工审核队列
3. Tier C 人工录入数据 → 从后台UI读取
4. 聚合各模块数据 → data/week-YYYY-WW.json
5. AI生成Executive Summary
6. 输出最终JSON → 前端自动加载
"""

import json
from datetime import datetime, timedelta
from collectors.central_bank import CentralBankCollector
from collectors.worldbank import WorldBankCollector
from collectors.real_estate import RealEstateCollector
from collectors.leading_indicators import LeadingIndicatorCollector
from collectors.social_signals import SocialSignalCollector
from collectors.commodities import CommodityCollector
from collectors.shipping import ShippingCollector
from collectors.trade_flow import TradeFlowCollector
from collectors.regulation import RegulationCollector
from collectors.innovation import InnovationCollector
from collectors.news_aggregator import NewsAggregator
from aggregators.country_profile import CountryProfileAggregator
from aggregators.executive_summary import SummaryGenerator

def run_weekly_pipeline():
    week_num = datetime.now().isocalendar()[1]
    year = datetime.now().year
    output_file = f"data/week-{year}-{week_num:02d}.json"

    # === Phase 1: 全自动采集 ===
    fed_rate = CentralBankCollector().collect_fed_rate()
    wb_data = WorldBankCollector().fetch_all()
    us_real_estate = RealEstateCollector().collect_us()
    us_construction = LeadingIndicatorCollector().collect_us_construction()
    gas_price = CommodityCollector().collect_natural_gas()
    metals_fred = CommodityCollector().collect_metals_fred()

    # === Phase 2: 半自动采集 + AI处理 ===
    global_rates = CentralBankCollector().collect_global_rates_summary()
    cn_real_estate = RealEstateCollector().collect_china()
    eu_real_estate = RealEstateCollector().collect_eurostat()
    scfi = ShippingCollector().collect_scfi()
    google_trends = SocialSignalCollector().collect_google_trends_batch()
    youtube_trends = SocialSignalCollector().collect_youtube_trends()
    news_macro = NewsAggregator().collect_macro_news()
    news_regulation = RegulationCollector().scan_regulatory_changes()
    innovations = InnovationCollector().collect_industry_news()

    # === Phase 3: 数据聚合 ===
    countries = CountryProfileAggregator().aggregate_all()
    summary = SummaryGenerator().generate(
        macro=news_macro, countries=countries,
        trends=google_trends, regulations=news_regulation
    )

    # === Phase 4: 组装周报JSON ===
    week_data = {
        "issue": week_num,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "title": "建材行业全球资讯期刊",
        "tagline": "Global Building Materials Weekly Intelligence Report",
        "coverage": "30+ 国家 | 35 品类 | 207+ HS编码",
        "sources": "16+ 数据源",
        "keyTakeaways": summary.takeaways,     # AI生成, 人工审核
        "macro": news_macro.articles,           # AI摘要+人工审核
        "regional": countries.by_region(),      # 自动聚合
        "trends": google_trends.product_trends, # 自动计算+人工筛选
        "supplyChain": [...],                    # 聚合
        "regulation": news_regulation.items,     # AI分类+人工审核
        "innovation": innovations.items,         # AI摘要
        "events": [...],                         # 混合来源
        "dataSources": [...]                     # 自动记录本次采集状态
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(week_data, f, ensure_ascii=False, indent=2)

    print(f"Weekly report generated: {output_file}")
```

#### 9.2 GitHub Actions 调度

```yaml
# .github/workflows/weekly-update.yml
name: Weekly Data Update
on:
  schedule:
    - cron: '0 8 * * 1'   # 每周一 UTC 8:00 (北京16:00)
  workflow_dispatch:        # 支持手动触发

jobs:
  collect-and-generate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run Tier A collectors
        env:
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
          YOUTUBE_API_KEY: ${{ secrets.YOUTUBE_API_KEY }}
          UN_COMTRADE_KEY: ${{ secrets.UN_COMTRADE_KEY }}
        run: python scripts/weekly_pipeline.py --tier a

      - name: Run Tier B collectors
        env:
          X_BEARER_TOKEN: ${{ secrets.X_BEARER_TOKEN }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: python scripts/weekly_pipeline.py --tier b

      - name: Generate weekly JSON
        run: python scripts/weekly_pipeline.py --assemble

      - name: Commit and push
        run: |
          git add data/
          git commit -m "Weekly update: $(date +%Y-W%V)" || echo "No changes"
          git push
```

---

### 十、数据源可靠性与降级策略

#### 10.1 数据源分级可靠性评估

| 可靠性 | 数据源 | 说明 |
|--------|--------|------|
| 高(稳定运行5年+) | World Bank API, FRED, Frankfurter, YouTube API | 官方维护, 有SLA, 极少宕机 |
| 中(偶有问题) | UN Comtrade, Eurostat, DBnomics | 偶有维护/迁移, 但总体可靠 |
| 低(随时可能失效) | pytrends, TradingEconomics抓取, SSE抓取 | 非官方/违反ToS, 需持续监控 |
| 人工依赖 | 投研报告, 行业会展, 买方卖方报告 | 无法自动化, 依赖行业关系 |

#### 10.2 降级策略

```
每个采集器实现 fallback chain:

primary_source() → secondary_source() → cached_data() → placeholder()

示例 - BDI指数:
  1. TradingEconomics抓取 (primary)
  2. Yahoo Finance ^BDI (secondary, 不稳定)
  3. 上周缓存值 + 标注"数据延迟" (cached)
  4. 显示"--" + 标注"待更新" (placeholder)
```

#### 10.3 数据质量检查

```python
# scripts/quality_check.py
class DataQualityChecker:
    def check(self, week_data):
        """每期数据生成后进行质量检查
        - 空值检查: 关键指标是否有缺失
        - 异常值检查: MoM变动>50%的指标标记为需审核
        - 时效性检查: 数据日期是否在合理范围内
        - 一致性检查: 同一指标不同来源的值是否一致
        输出: 质量报告, 标记需人工审核的条目
        """
```

---

### 十一、API Key 注册清单

开始开发前需要注册的免费/付费API:

| API | 费用 | 注册地址 | 用途 |
|-----|------|----------|------|
| FRED | 免费 | fred.stlouisfed.org/docs/api/api_key.html | 美国经济/房价/PMI |
| YouTube Data v3 | 免费(10K单位/天) | console.cloud.google.com | 视频趋势 |
| UN Comtrade | 免费(有限额) | comtradedeveloper.un.org | 贸易流数据 |
| World Bank | 免费(无需注册) | -- | 基础经济指标 |
| Frankfurter | 免费(无需注册) | -- | 汇率 |
| X API Basic | $100/月 | developer.x.com | 社交信号 |
| SerpAPI(备选) | $50/月 | serpapi.com | Google Trends备选 |
| OpenAI API | 按量付费 | platform.openai.com | AI摘要/分类/翻译 |

---

### 十二、开发优先级建议

| 优先级 | 模块 | 理由 |
|--------|------|------|
| P0(首周) | central_bank + worldbank + real_estate(US) | 核心宏观+最重要的国别数据 |
| P1(第2周) | commodities + shipping + social_signals | 供应链和产品趋势差异化内容 |
| P2(第3周) | trade_flow + regulation + news_aggregator | 贸易和监管深度 |
| P3(第4周) | innovation + emerging_demand + research_reports | 前瞻性内容 |
| P4(持续) | 更多国别数据 + 数据质量优化 + UI增强 | 覆盖面扩展 |

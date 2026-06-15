"""全局配置: API Keys, 国家列表, FRED Series ID"""
import os

# === API Keys (从环境变量读取, 本地开发可在此处临时填写) ===
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")

# === 国家列表 (ISO 3166-1 alpha-2) ===
# World Bank 和 FRED 都使用此代码
COUNTRIES = {
    # 亚太
    "CN": {"zh": "中国", "region": "亚太"},
    "IN": {"zh": "印度", "region": "亚太"},
    "JP": {"zh": "日本", "region": "亚太"},
    "KR": {"zh": "韩国", "region": "亚太"},
    "ID": {"zh": "印尼", "region": "亚太"},
    "VN": {"zh": "越南", "region": "亚太"},
    "PH": {"zh": "菲律宾", "region": "亚太"},
    "TH": {"zh": "泰国", "region": "亚太"},
    "AU": {"zh": "澳大利亚", "region": "亚太"},
    # 中东非洲
    "SA": {"zh": "沙特", "region": "中东非洲"},
    "AE": {"zh": "阿联酋", "region": "中东非洲"},
    "NG": {"zh": "尼日利亚", "region": "中东非洲"},
    "ZA": {"zh": "南非", "region": "中东非洲"},
    "EG": {"zh": "埃及", "region": "中东非洲"},
    # 欧洲
    "DE": {"zh": "德国", "region": "欧洲"},
    "GB": {"zh": "英国", "region": "欧洲"},
    "FR": {"zh": "法国", "region": "欧洲"},
    "PL": {"zh": "波兰", "region": "欧洲"},
    "TR": {"zh": "土耳其", "region": "欧洲"},
    "IT": {"zh": "意大利", "region": "欧洲"},
    "ES": {"zh": "西班牙", "region": "欧洲"},
    # 美洲
    "US": {"zh": "美国", "region": "美洲"},
    "BR": {"zh": "巴西", "region": "美洲"},
    "MX": {"zh": "墨西哥", "region": "美洲"},
    "CA": {"zh": "加拿大", "region": "美洲"},
}

# 区域分组
REGIONS = ["亚太", "中东非洲", "欧洲", "美洲"]
COUNTRIES_BY_REGION = {}
for code, info in COUNTRIES.items():
    r = info["region"]
    COUNTRIES_BY_REGION.setdefault(r, []).append(code)

# === World Bank 指标 ===
WB_INDICATORS = {
    "gdp_nominal": "NY.GDP.MKTP.CD",       # GDP(现价美元)
    "gdp_growth": "NY.GDP.MKTP.KD.ZG",     # GDP增速(%)
    "population": "SP.POP.TOTL",            # 人口
    "urbanization": "SP.URB.TOTL.IN.ZS",    # 城市化率(%)
    "cpi_inflation": "FP.CPI.TOTL.ZG",      # CPI通胀(%)
    "construction_va": "NV.IND.TOTL.ZS",    # 工业附加值占比(建筑相关)
}

# === FRED Series ID ===
FRED_SERIES = {
    # 央行利率
    "fed_funds_rate": "DFF",                 # 联邦基金有效利率(日)
    "fed_funds_target_upper": "DFII10",      # 联邦基金目标利率上限
    "fed_funds_target_lower": "DFII10",      # (用同一series,手动区分)
    # 美国房地产 - Case-Shiller
    "cs_national_sa": "CSUSHPINSA",          # 全美房价指数(季调)
    "cs_national_yoy": "CSUSHPINSAYOY",      # 全美房价同比(%)
    "cs_20city": "SPCS20RSA",                # 20城综合(季调)
    "cs_20city_yoy": "SPCS20RNSAYOY",        # 20城同比
    # 美国建筑先行指标
    "building_permits": "PERMIT",            # 建筑许可证(千套,SAAR)
    "housing_starts": "HOUST",               # 新屋开工(千套,SAAR)
    "construction_spending": "TLACONS",      # 建筑支出(十亿美元,SA)
    "existing_home_sales": "EXHOSLUSM495S",  # 成屋销售(万套,SAAR)
    "existing_home_inventory": "MSACSR",     # 成屋库存(月数)
    "new_home_sales": "HSN1FNSA",            # 新房销售(千套,SA)
    "home_price_index_ofheo": "OFHEOPRICE",  # OFHEO房价指数
    # 美国宏观
    "us_cpi_all": "CPIAUCSL",               # CPI全品类
    "us_cpi_shelter": "CUSR0000SAH1",        # CPI住房分项
    "us_unemployment": "UNRATE",             # 失业率
    "us_10y_treasury": "DGS10",              # 10年期国债
    "us_30y_mortgage": "MORTGAGE30US",       # 30年期房贷利率
    "us_15y_mortgage": "MORTGAGE15US",       # 15年期房贷利率
    # 金属价格(FRED有部分)
    "aluminum_price": "PALUM",               # 铝全球均价($/mt)
    "copper_price": "PCOPP",                 # 铜($/mt)
    "zinc_price": "PZINC",                   # 锌
    "lead_price": "PLEAD",                   # 铅
    "tin_price": "PTIN",                     # 锡
    "nickel_price": "PNICK",                 # 镍
    "iron_ore": "PIORECR",                   # 铁矿石
    # 能源
    "natural_gas_hh": "NGRNGC1",             # 天然气Henry Hub
    "wti_crude": "DCOILWTICO",               # WTI原油
    "brent_crude": "DCOILBRENTEU",           # Brent原油
    "coal": "PCOALAU",                       # 澳大利亚动力煤
}

# === 央行利率映射 (FRED series_id) ===
CENTRAL_BANK_RATES = {
    "US": {"name": "美联储(Fed)", "fred_id": "DFF", "type": "daily"},
    "ECB": {"name": "欧央行(ECB)", "fred_id": "ECBESTRVOL", "type": "daily"},
    "GB": {"name": "英央行(BOE)", "fred_id": "IUDSOIA", "type": "daily"},
    "JP": {"name": "日央行(BOJ)", "fred_id": "IRSTCI01JPM156N", "type": "monthly"},
    "CN_1Y": {"name": "中国LPR(1Y)", "fred_id": "CHN_LPR_1Y", "type": "monthly"},  # 可能不存在
    "AU": {"name": "澳联储(RBA)", "fred_id": "IRSTCI01AUM156N", "type": "monthly"},
    "CA": {"name": "加央行(BOC)", "fred_id": "IRSTCI01CAM156N", "type": "monthly"},
    "BR": {"name": "巴西央行(BCB)", "fred_id": "IRSTCI01BRM156N", "type": "monthly"},
    "IN": {"name": "印度央行(RBI)", "fred_id": "IRSTCI01INM156N", "type": "monthly"},
    "KR": {"name": "韩央行(BOK)", "fred_id": "IRSTCI01KRM156N", "type": "monthly"},
}

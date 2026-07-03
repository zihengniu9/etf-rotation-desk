import re

import pandas as pd


THEME_PATTERNS: list[tuple[str, str]] = [
    (r"沪深300|300ETF|HS300", "沪深300"),
    (r"中证500|500ETF", "中证500"),
    (r"中证1000|1000ETF", "中证1000"),
    (r"科创.*(半导体|芯片)|(半导体|芯片).*科创", "科创半导体"),
    (r"中韩.*(半导体|芯片)|(半导体|芯片).*中韩", "中韩半导体"),
    (r"科创50|科创板|科创100|科创综指|科创200|科创价格", "科创"),
    (r"上证50|^.*[^科创板]50ETF", "上证50"),
    (r"创业板|创成长|创业板50", "创业板"),
    (r"红利|股息|红利低波", "红利"),
    (r"央企|国企|中特估", "央国企"),
    (r"半导体|芯片|集成电路|电子50|电子ETF", "半导体"),
    (r"机器人", "机器人"),
    (r"人工智能|AI|算力|云计算|大数据|数据中心", "AI算力"),
    (r"数字经济|信息技术|科技龙头|智能制造|G60创新|科技引领|成长100|科技优势|研发创新|战略新兴", "科技成长"),
    (r"通信|5G|CPO|光通信", "通信"),
    (r"软件|信创|计算机", "计算机"),
    (r"传媒|游戏|动漫|影视", "传媒游戏"),
    (r"白银", "白银"),
    (r"原油|油气", "原油"),
    (r"证券|券商|金融科技", "证券"),
    (r"银行", "银行"),
    (r"保险", "保险"),
    (r"军工|国防|航天|航空", "军工"),
    (r"新能源车|新能车|智能车|汽车|电池|锂电", "新能源车"),
    (r"光伏|太阳能", "光伏"),
    (r"储能|电力设备|新能源", "新能源"),
    (r"医药|医疗|创新药|生物|疫苗|中药", "医药"),
    (r"消费|食品|饮料|酒|白酒|农业|养殖", "消费"),
    (r"家电|家具|家居", "家电家居"),
    (r"旅游|酒店|餐饮", "旅游酒店"),
    (r"煤炭|能源", "煤炭能源"),
    (r"有色|稀土|金属|矿业|钢铁", "资源金属"),
    (r"化工|材料|新材料", "化工材料"),
    (r"房地产|地产", "房地产"),
    (r"基建|建筑|建材|工程", "基建建材"),
    (r"物流|运输|港口|航运", "交通运输"),
    (r"环保|碳中和|绿色", "环保低碳"),
    (r"国债|政金债|地方债|科创债|信用债|公司债|转债|可转债|短融|债", "债券"),
    (r"黄金|金ETF", "黄金"),
    (r"纳指|纳斯达克|NASDAQ", "纳指"),
    (r"标普|S&P|SP500", "标普500"),
    (r"日经|日本", "日经"),
    (r"德国|法国|海外|全球", "海外宽基"),
    (r"恒生科技|港股通科技|港股科技", "港股科技"),
    (r"恒生|港股通|H股|香港", "港股宽基"),
    (r"货币|现金|添利|银华日利", "货币"),
]

PROVIDER_WORDS = [
    "华夏",
    "易方达",
    "华泰柏瑞",
    "国泰",
    "富国",
    "南方",
    "广发",
    "博时",
    "嘉实",
    "招商",
    "鹏华",
    "汇添富",
    "银华",
    "天弘",
    "华安",
    "国联安",
    "景顺长城",
    "大成",
    "工银",
    "建信",
    "平安",
    "中银",
    "兴业",
    "海富通",
    "华宝",
    "华富",
    "永赢",
    "摩根",
    "东财",
]


def normalize_etf_code(value: object) -> str:
    text = str(value).strip()
    if "." in text:
        text = text.split(".")[0]
    digits = re.sub(r"\D", "", text)
    return digits.zfill(6)[-6:]


def extract_theme(name: object) -> str:
    text = str(name).upper().strip()
    for pattern, theme in THEME_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return theme
    return _fallback_theme(str(name))


def build_theme_pool(etfs: pd.DataFrame, scales: pd.DataFrame) -> pd.DataFrame:
    frame = _normalize_etf_list(etfs)
    scale_frame = _normalize_scale_list(scales)
    merged = frame.merge(scale_frame, on="code", how="left")
    merged["shares"] = pd.to_numeric(merged["shares"], errors="coerce")
    merged["latest_nav"] = pd.to_numeric(merged["latest_nav"], errors="coerce")
    merged["fund_size"] = merged["shares"] * merged["latest_nav"]
    merged["capacity_source"] = merged["fund_size"].map(lambda value: "fund_size" if pd.notna(value) else "missing")
    merged["theme"] = merged["name"].map(extract_theme)
    merged = merged[merged["code"].str.startswith(("1", "5"))]
    merged = merged.dropna(subset=["theme"])
    merged = merged.sort_values(["theme", "fund_size"], ascending=[True, False], na_position="last")
    pool = merged.drop_duplicates(subset=["theme"], keep="first").reset_index(drop=True)
    columns = [
        "theme",
        "code",
        "name",
        "latest_nav",
        "shares",
        "fund_size",
        "scale_source",
        "capacity_source",
        "fund_type",
        "query_date",
    ]
    return pool[[column for column in columns if column in pool.columns]]


def _normalize_etf_list(etfs: pd.DataFrame) -> pd.DataFrame:
    rename_map = {
        "基金代码": "code",
        "基金名称": "name",
        "基金简称": "name",
        "最新-单位净值": "latest_nav",
        "当前-单位净值": "latest_nav",
        "基金类型": "fund_type",
        "类型": "fund_type",
        "查询日期": "query_date",
    }
    frame = etfs.rename(columns=rename_map).copy()
    required = {"code", "name"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"ETF list missing columns: {', '.join(sorted(missing))}")
    if "latest_nav" not in frame.columns:
        frame["latest_nav"] = pd.NA
    frame["code"] = frame["code"].map(normalize_etf_code)
    frame["name"] = frame["name"].astype(str).str.strip()
    return frame


def _normalize_scale_list(scales: pd.DataFrame) -> pd.DataFrame:
    rename_map = {
        "基金代码": "code",
        "基金份额": "shares",
        "净值": "latest_nav_from_scale",
    }
    frame = scales.rename(columns=rename_map).copy()
    if "code" not in frame.columns:
        raise ValueError("scale list missing code column")
    if "shares" not in frame.columns:
        frame["shares"] = pd.NA
    if "scale_source" not in frame.columns:
        frame["scale_source"] = ""
    frame["code"] = frame["code"].map(normalize_etf_code)
    return frame[["code", "shares", "scale_source"]].drop_duplicates(subset=["code"], keep="first")


def _fallback_theme(name: str) -> str:
    text = name
    for word in PROVIDER_WORDS:
        text = text.replace(word, "")
    text = re.sub(r"交易型开放式指数证券投资基金|ETF联接|ETF|指数|增强|发起式|基金", "", text, flags=re.IGNORECASE)
    text = re.sub(r"中证|国证|上证|深证|CS|A股|主题|产业", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[\s（）()A-Z0-9]+", "", text).strip("-_ ")
    return text[:12] if text else name[:12]

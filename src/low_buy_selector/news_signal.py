"""消息面检测：把快讯归类到大盘 / 主题，给出利好利空与进攻门控建议。

规则只用关键词和来源自带的重要级别，结果可解释、可复核：
- 每条消息记录命中的关键词，页面可以直接展示“为什么判为利空”；
- 消息面只能“踩刹车”（阻断或提示进攻模式），不能单独把任何模式推成进攻；
- 采集失败或数据过期时页面显示“未接入/过期”，不参与判定，也不伪造中性结论。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
import re
from typing import Iterable

VERSION = "news-signal-v1"
LOOKBACK_HOURS = 24
HALF_LIFE_HOURS = 12.0

# 主题词典：key 与看板 themeKey() 的结果对齐；aliases 用于匹配 ETF 主题名、行业名和短线题材名。
THEMES: dict[str, dict[str, list[str]]] = {
    "半导体": {"aliases": ["半导体", "芯片", "集成电路", "科创芯片"], "words": ["半导体", "芯片", "英伟达", "台积电", "光刻机", "集成电路", "晶圆", "光刻", "存储芯片", "封测", "EDA", "先进制程"]},
    "人工智能": {"aliases": ["人工智能", "AI", "计算机", "软件", "IT服务", "云计算", "大数据"], "words": ["人工智能", "大模型", "AI", "算力", "智算", "数据中心", "软件", "信创", "云计算"]},
    "通信": {"aliases": ["通信", "5G", "光模块", "光电"], "words": ["通信", "5G", "6G", "光模块", "CPO", "运营商", "卫星互联网"]},
    "机器人": {"aliases": ["机器人", "自动化"], "words": ["机器人", "人形机器人", "减速器", "具身智能"]},
    "医药": {"aliases": ["医药", "创新药", "中药", "制药", "生物", "医疗"], "words": ["医药", "创新药", "集采", "医保", "药品", "医疗器械", "疫苗", "CXO", "生物药", "临床"]},
    "证券": {"aliases": ["证券", "券商", "非银", "多元金融"], "words": ["券商", "证券公司", "两融", "融资融券", "并购重组"]},
    "银行": {"aliases": ["银行"], "words": ["银行", "存款利率", "净息差", "不良贷款"]},
    "保险": {"aliases": ["保险"], "words": ["保险", "险资"]},
    "红利": {"aliases": ["红利", "高股息", "央企", "防守"], "words": ["红利", "高股息", "分红", "市值管理", "中特估"]},
    "黄金": {"aliases": ["黄金", "贵金属"], "words": ["黄金", "金价", "贵金属", "白银"]},
    "有色": {"aliases": ["有色", "工业金属", "铜", "铝", "小金属", "能源金属", "稀土"], "words": ["有色", "铜价", "铝价", "稀土", "锂价", "钴", "镍", "钨"]},
    "新能源": {"aliases": ["新能源", "光伏", "风电", "电池", "锂电", "储能", "电网"], "words": ["光伏", "风电", "储能", "锂电", "动力电池", "新能源", "电网", "特高压", "多晶硅"]},
    "汽车": {"aliases": ["汽车", "新能源车", "智能驾驶"], "words": ["汽车", "新能源车", "智能驾驶", "自动驾驶", "车企", "以旧换新"]},
    "军工": {"aliases": ["军工", "国防", "航天", "航空"], "words": ["军工", "国防", "航天", "航空发动机", "无人机", "低空经济"]},
    "消费": {"aliases": ["消费", "白酒", "食品", "饮料", "家电", "零售", "旅游"], "words": ["消费", "白酒", "零售", "家电", "旅游", "免税", "社零", "消费券"]},
    "地产": {"aliases": ["房地产", "地产", "建筑", "建材"], "words": ["房地产", "楼市", "房贷", "限购", "保交楼", "城中村", "建材"]},
    "煤炭": {"aliases": ["煤炭", "能源"], "words": ["煤炭", "煤价", "动力煤", "焦煤"]},
    "石油": {"aliases": ["石油", "油气", "化工"], "words": ["原油", "油价", "OPEC", "天然气"]},
    "电力": {"aliases": ["电力", "公用事业", "燃气"], "words": ["电力", "电价", "核电", "水电", "火电"]},
    "传媒": {"aliases": ["传媒", "游戏", "影视", "文化"], "words": ["游戏版号", "游戏", "影视", "短剧", "传媒"]},
    "农业": {"aliases": ["农业", "养殖", "种植", "农产品"], "words": ["猪价", "生猪", "粮食", "种业", "养殖"]},
    "纳指": {"aliases": ["纳指", "纳斯达克", "美股", "标普"], "words": ["纳斯达克", "纳指", "美股", "标普500", "道指"]},
    "港股": {"aliases": ["港股", "恒生", "中概"], "words": ["港股", "恒生指数", "恒生科技", "中概股", "南向资金"]},
}

# 影响全市场的消息：政策、监管、宏观、外部冲击。
MARKET_WORDS = [
    "央行", "人民银行", "降准", "降息", "LPR", "MLF", "逆回购", "证监会", "国务院", "政治局", "财政部", "发改委",
    "印花税", "IPO", "减持新规", "汇率", "人民币", "美联储", "加息", "关税", "制裁", "出口管制", "地缘", "冲突",
    "中东", "以色列", "伊朗", "俄乌", "台海", "GDP", "CPI", "PPI", "PMI", "社融", "M2", "国常会", "汇金", "平准基金", "国家队", "A股", "沪指", "大盘",
]
AUTHORITY_WORDS = ["国务院", "政治局", "央行", "人民银行", "证监会", "财政部", "发改委", "国常会", "美联储", "汇金", "商务部"]

POSITIVE_WORDS = [
    "利好", "降准", "降息", "支持", "鼓励", "提振", "刺激", "放宽", "超预期", "增持", "回购", "获批", "中标", "补贴",
    "创新高", "突破", "扩大", "加快", "推进", "稳定", "上调评级", "签约", "订单", "增长", "复苏",
    "达成协议", "入市", "护盘", "回暖", "企稳", "加大", "逆周期", "特别国债", "止跌",
]
NEGATIVE_WORDS = [
    "利空", "制裁", "加征", "出口管制", "调查", "立案", "处罚", "暴跌", "下调", "收紧", "限制",
    "减持", "爆雷", "违约", "退市", "冲突", "战争", "袭击", "禁止", "不及预期", "下滑", "亏损", "加息", "缩表",
    "暂停", "叫停", "问询", "风险警示", "跳水", "恐慌", "降价", "列入实体清单", "反倾销", "通报批评", "监管函",
]
# 固定短语先整体判定（0 表示中性，只去掉不计分）再从文本里去掉，避免“取消加征关税”命中“加征”、“下调存款准备金率”命中“下调”。
PHRASES: dict[str, int] = {
    "暂缓加征": 1, "取消加征": 1, "暂停加征": 1, "关税下调": 1, "下调关税": 1, "豁免": 1, "停火": 1, "解除制裁": 1,
    "放宽限制": 1, "取消限制": 1, "不减持": 1, "下调存款准备金率": 1, "下调准备金": 1, "下调利率": 1, "下调LPR": 1,
    "下调印花税": 1, "降低印花税": 1, "下调首付": 1, "下调房贷利率": 1, "降低融资成本": 1,
    "局势升级": -1, "冲突升级": -1, "制裁升级": -1, "下调存款利率": 0, "存款利率下调": 0,
    "下调评级": -1, "下调目标价": -1, "下调盈利预测": -1, "加征关税": -1, "扩大出口管制": -1, "暂停上市": -1,
}
# 冲击性事件：命中时权重 +1（与权威来源加成同样封顶 3）。
SEVERE_WORDS = ["加征关税", "出口管制", "制裁", "战争", "熔断", "违约", "暴跌", "实体清单", "断供"]

# 盘面复述（收评、午评、指数涨跌播报）已由行情模块覆盖，消息面不重复计分。
RECAP_PATTERN = re.compile(r"(收评|午评|早评|开盘[：:]|收盘[：:]|盘中|午间|集合竞价|沪指|深成指|创业板指|恒指|指数).{0,12}(涨|跌|收|报|翻红|翻绿)")

GATE_BLOCK_SCORE = -6.0
GATE_CAUTION_SCORE = -3.0
THEME_ALERT_SCORE = -3.0


@dataclass
class NewsItem:
    source: str
    published_at: datetime
    title: str
    content: str = ""
    url: str = ""
    level: int = 1  # 1 普通、2 重要、3 头条/加红
    tags: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return f"{self.title} {self.content}".strip()


def normalize_title(text: str) -> str:
    text = re.sub(r"【|】|\[|\]|（|）|\(|\)|\s|，|。|、|：|:|；|;|“|”|\"|'", "", text or "")
    text = re.sub(r"^(财联社|东方财富|新浪财经|格隆汇|智通财经)\d*月?\d*日?电?", "", text)
    return text[:60]


def headline(item: NewsItem) -> str:
    title = (item.title or "").strip()
    if title:
        return title
    content = (item.content or "").strip()
    match = re.match(r"【(.+?)】", content)
    if match:
        return match.group(1)
    return content[:60] + ("…" if len(content) > 60 else "")


def bigrams(text: str) -> set[str]:
    return {text[i:i + 2] for i in range(max(len(text) - 1, 0))}


def dedupe(items: Iterable[NewsItem]) -> list[NewsItem]:
    """多源同一事件只保留重要级别最高、时间最早的一条。"""
    kept: list[tuple[NewsItem, set[str]]] = []
    for item in sorted(items, key=lambda x: (-x.level, x.published_at)):
        key = normalize_title(headline(item) + item.content[:40])
        grams = bigrams(key)
        duplicate = False
        for other, other_grams in kept:
            union = grams | other_grams
            if union and len(grams & other_grams) / len(union) >= 0.6:
                duplicate = True
                if item.source not in other.tags:
                    other.tags.append(item.source)
                break
        if not duplicate:
            kept.append((item, grams))
    return sorted((item for item, _ in kept), key=lambda x: x.published_at, reverse=True)


def find_words(text: str, words: Iterable[str]) -> list[str]:
    lower = text.lower()
    return [word for word in words if word.lower() in lower]


def classify(item: NewsItem, now: datetime) -> dict | None:
    text = item.text
    if RECAP_PATTERN.search(headline(item)):
        return None
    themes = [key for key, spec in THEMES.items() if find_words(text, spec["words"])]
    market_hits = find_words(text, MARKET_WORDS)
    if not themes and not market_hits:
        return None
    stripped = text
    phrase_pos, phrase_neg = [], []
    for phrase in sorted(PHRASES, key=len, reverse=True):
        if phrase.lower() in stripped.lower():
            if PHRASES[phrase]:
                (phrase_pos if PHRASES[phrase] > 0 else phrase_neg).append(phrase)
            stripped = re.sub(re.escape(phrase), " ", stripped, flags=re.I)
    positive = phrase_pos + find_words(stripped, POSITIVE_WORDS)
    negative = phrase_neg + find_words(stripped, NEGATIVE_WORDS)
    polarity = len(positive) - len(negative)
    sentiment = 1 if polarity > 0 else -1 if polarity < 0 else 0
    authority = find_words(text, AUTHORITY_WORDS)
    severe = find_words(text, SEVERE_WORDS)
    weight = max(1, min(3, item.level + (1 if authority else 0) + (1 if severe and sentiment < 0 else 0)))
    age_hours = max(0.0, (now - item.published_at).total_seconds() / 3600)
    decay = 0.5 ** (age_hours / HALF_LIFE_HOURS)
    scope = "market" if market_hits and (authority or not themes or len(market_hits) >= 2) else "theme"
    return {
        "id": hashlib.sha1(f"{item.source}|{headline(item)}|{item.published_at.isoformat()}".encode("utf-8")).hexdigest()[:12],
        "source": item.source,
        "also_in": [tag for tag in item.tags if tag != item.source],
        "published_at": item.published_at.isoformat(timespec="minutes"),
        "age_hours": round(age_hours, 1),
        "title": headline(item),
        "url": item.url,
        "scope": scope,
        "themes": themes,
        "sentiment": sentiment,
        "weight": weight,
        "impact": round(sentiment * weight * decay, 3),
        "evidence": {"positive": positive, "negative": negative, "market": market_hits, "authority": authority, "severe": severe},
    }


def aggregate(items: Iterable[NewsItem], now: datetime, sources: list[dict], lookback_hours: int = LOOKBACK_HOURS) -> dict:
    start = now - timedelta(hours=lookback_hours)
    window = [item for item in items if start <= item.published_at <= now + timedelta(minutes=5)]
    unique = dedupe(window)
    classified = [row for row in (classify(item, now) for item in unique) if row]

    market_rows = [row for row in classified if row["scope"] == "market"]
    market_score = round(sum(row["impact"] for row in market_rows), 2)
    theme_scores: dict[str, dict] = {}
    for row in classified:
        for theme in row["themes"]:
            bucket = theme_scores.setdefault(theme, {"theme": theme, "aliases": THEMES[theme]["aliases"], "score": 0.0, "positive": 0, "negative": 0, "items": []})
            bucket["score"] += row["impact"]
            bucket["positive"] += row["sentiment"] > 0
            bucket["negative"] += row["sentiment"] < 0
            if len(bucket["items"]) < 3:
                bucket["items"].append(row["id"])
    themes = sorted(
        ({**value, "score": round(value["score"], 2), "alert": value["score"] <= THEME_ALERT_SCORE} for value in theme_scores.values()),
        key=lambda value: value["score"],
    )

    major = [row for row in market_rows if row["sentiment"] < 0 and row["weight"] >= 3 and row["age_hours"] <= 18]
    reasons: list[str] = []
    ok_sources = [source for source in sources if source.get("status") == "ok"]
    if not ok_sources:
        state = "unavailable"
        reasons.append("所有消息源采集失败，消息面未参与判定")
    elif major or market_score <= GATE_BLOCK_SCORE:
        state = "block"
        if major:
            reasons.append("重大利空：" + major[0]["title"])
        if market_score <= GATE_BLOCK_SCORE:
            reasons.append(f"大盘消息净分 {market_score} ≤ {GATE_BLOCK_SCORE}")
    elif market_score <= GATE_CAUTION_SCORE or any(row["sentiment"] < 0 and row["weight"] >= 2 for row in market_rows):
        state = "caution"
        if market_score <= GATE_CAUTION_SCORE:
            reasons.append(f"大盘消息净分 {market_score} 偏空")
        heavy = [row for row in market_rows if row["sentiment"] < 0 and row["weight"] >= 2]
        if heavy:
            reasons.append("重要利空：" + heavy[0]["title"])
    else:
        state = "clear"
        reasons.append("未发现影响全市场的重要利空")

    important = sorted(classified, key=lambda row: (-abs(row["impact"]), row["age_hours"]))[:20]
    return {
        "version": VERSION,
        "generated_at": now.isoformat(timespec="seconds"),
        "window": {"start": start.isoformat(timespec="minutes"), "end": now.isoformat(timespec="minutes"), "hours": lookback_hours, "half_life_hours": HALF_LIFE_HOURS},
        "status": "ok" if ok_sources else "error",
        "sources": sources,
        "counts": {"fetched": len(window), "unique": len(unique), "relevant": len(classified), "market": len(market_rows)},
        "market": {"score": market_score, "positive": sum(r["sentiment"] > 0 for r in market_rows), "negative": sum(r["sentiment"] < 0 for r in market_rows)},
        "gate": {
            "state": state,
            "reasons": reasons,
            "rule": f"重大利空（权重3且18小时内）或大盘净分≤{GATE_BLOCK_SCORE} → 阻断进攻；净分≤{GATE_CAUTION_SCORE}或有重要利空 → 提示；主题净分≤{THEME_ALERT_SCORE} → 该主题对应模式暂停。利好消息不单独触发进攻。",
        },
        "themes": themes,
        "items": important,
    }

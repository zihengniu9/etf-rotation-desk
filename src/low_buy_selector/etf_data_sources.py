from contextlib import contextmanager
from io import BytesIO
from datetime import date
import re
import warnings

import pandas as pd
warnings.filterwarnings("ignore", message=".*urllib3.*chardet.*")
warnings.filterwarnings("ignore", message="Workbook contains no default style.*")
import requests

from .etf_pool import normalize_etf_code


REALTIME_QUOTE_COLUMNS = ["code", "name", "realtime_price", "realtime_date", "realtime_updated_at"]
SINA_QUOTE_URL = "https://hq.sinajs.cn/list={symbols}"
SINA_QUOTE_CHUNK_SIZE = 120


def fetch_all_etfs() -> pd.DataFrame:
    with _quiet_akshare():
        import akshare as ak

        frame = ak.fund_etf_spot_ths(date="")
    return frame.rename(
        columns={
            "基金代码": "code",
            "基金名称": "name",
            "最新-单位净值": "latest_nav",
            "当前-单位净值": "current_nav",
            "基金类型": "fund_type",
            "查询日期": "query_date",
        }
    )


def fetch_realtime_etf_quotes(codes: list[str] | None = None) -> pd.DataFrame:
    if codes:
        sina = fetch_sina_realtime_etf_quotes(codes)
        if not sina.empty:
            return sina
    with _quiet_akshare():
        import akshare as ak

        try:
            frame = ak.fund_etf_spot_em()
        except Exception:
            return pd.DataFrame(columns=REALTIME_QUOTE_COLUMNS)
    return normalize_realtime_etf_quotes(frame)


def fetch_sina_realtime_etf_quotes(codes: list[str], *, chunk_size: int = SINA_QUOTE_CHUNK_SIZE) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    normalized_codes = [normalize_etf_code(code) for code in codes]
    normalized_codes = [code for code in dict.fromkeys(normalized_codes) if code]
    headers = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
    for start in range(0, len(normalized_codes), chunk_size):
        chunk = normalized_codes[start : start + chunk_size]
        symbols = ",".join(to_sina_symbol(code) for code in chunk)
        if not symbols:
            continue
        try:
            response = requests.get(SINA_QUOTE_URL.format(symbols=symbols), headers=headers, timeout=20)
            response.raise_for_status()
        except Exception:
            continue
        response.encoding = "gb18030"
        parsed = parse_sina_realtime_quotes(response.text)
        if not parsed.empty:
            rows.append(parsed)
    if not rows:
        return pd.DataFrame(columns=REALTIME_QUOTE_COLUMNS)
    return pd.concat(rows, ignore_index=True).drop_duplicates(subset=["code"], keep="first").reset_index(drop=True)


def parse_sina_realtime_quotes(text: str) -> pd.DataFrame:
    rows: list[dict] = []
    pattern = re.compile(r"var hq_str_(?P<symbol>s[hz]\d{6})=\"(?P<body>[^\"]*)\";")
    for match in pattern.finditer(text or ""):
        symbol = match.group("symbol")
        values = match.group("body").split(",")
        if len(values) < 32:
            continue
        code = normalize_etf_code(symbol)
        price = pd.to_numeric(pd.Series([values[3]]), errors="coerce").iloc[0]
        quote_date = values[30].strip()
        quote_time = values[31].strip()
        if pd.isna(price) or not quote_date:
            continue
        rows.append(
            {
                "code": code,
                "name": values[0].strip(),
                "realtime_price": float(price),
                "realtime_date": quote_date,
                "realtime_updated_at": f"{quote_date} {quote_time}".strip(),
            }
        )
    if not rows:
        return pd.DataFrame(columns=REALTIME_QUOTE_COLUMNS)
    frame = pd.DataFrame(rows)
    frame["realtime_date"] = pd.to_datetime(frame["realtime_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    frame["realtime_updated_at"] = pd.to_datetime(frame["realtime_updated_at"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")
    frame = frame.dropna(subset=["realtime_price", "realtime_date"])
    frame = frame[frame["realtime_price"] > 0]
    return frame[REALTIME_QUOTE_COLUMNS].drop_duplicates(subset=["code"], keep="first").reset_index(drop=True)


def normalize_realtime_etf_quotes(frame: pd.DataFrame, *, as_of: date | None = None) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=REALTIME_QUOTE_COLUMNS)
    quote_date = (as_of or date.today()).strftime("%Y-%m-%d")
    quote_updated_at = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    rename_map = {
        "代码": "code",
        "名称": "name",
        "最新价": "realtime_price",
        "数据日期": "realtime_date",
        "更新时间": "realtime_updated_at",
    }
    normalized = frame.rename(columns=rename_map).copy()
    if "code" not in normalized.columns or "realtime_price" not in normalized.columns:
        return pd.DataFrame(columns=REALTIME_QUOTE_COLUMNS)
    if "name" not in normalized.columns:
        normalized["name"] = ""
    if "realtime_date" not in normalized.columns:
        normalized["realtime_date"] = quote_date
    if "realtime_updated_at" not in normalized.columns:
        normalized["realtime_updated_at"] = quote_updated_at
    normalized["code"] = normalized["code"].map(normalize_etf_code)
    normalized["realtime_price"] = pd.to_numeric(normalized["realtime_price"], errors="coerce")
    normalized["realtime_date"] = pd.to_datetime(normalized["realtime_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    normalized["realtime_updated_at"] = pd.to_datetime(normalized["realtime_updated_at"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")
    normalized = normalized.dropna(subset=["code", "realtime_price", "realtime_date"])
    normalized = normalized[normalized["realtime_price"] > 0]
    return normalized[REALTIME_QUOTE_COLUMNS].drop_duplicates(subset=["code"], keep="first").reset_index(drop=True)


def fetch_etf_scales(stat_date: str | None = None) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    sse = fetch_sse_etf_scales(stat_date=stat_date)
    if not sse.empty:
        frames.append(sse)
    szse = fetch_szse_etf_scales()
    if not szse.empty:
        frames.append(szse)
    if not frames:
        return pd.DataFrame(columns=["code", "shares", "scale_source"])
    result = pd.concat(frames, ignore_index=True)
    result["code"] = result["code"].map(normalize_etf_code)
    result["shares"] = pd.to_numeric(result["shares"], errors="coerce")
    return result.dropna(subset=["code"]).drop_duplicates(subset=["code"], keep="first")


def fetch_sse_etf_scales(stat_date: str | None = None) -> pd.DataFrame:
    date_text = stat_date or date.today().strftime("%Y%m%d")
    with _quiet_akshare():
        import akshare as ak

        try:
            frame = ak.fund_etf_scale_sse(date=date_text)
        except Exception:
            return pd.DataFrame(columns=["code", "shares", "scale_source"])
    frame = frame.rename(columns={"基金代码": "code", "基金份额": "shares"}).copy()
    frame["scale_source"] = "sse_shares"
    return frame[["code", "shares", "scale_source"]]


def fetch_szse_etf_scales() -> pd.DataFrame:
    url = "https://fund.szse.cn/api/report/ShowReport"
    params = {
        "SHOWTYPE": "xlsx",
        "CATALOGID": "1000_lf",
        "TABKEY": "tab1",
        "random": "0.07610353191740105",
    }
    headers = {
        "Referer": "https://fund.szse.cn/marketdata/fundslist/index.html",
        "User-Agent": "Mozilla/5.0",
    }
    try:
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        frame = pd.read_excel(BytesIO(response.content), engine="openpyxl", dtype={"基金代码": str})
    except Exception:
        return pd.DataFrame(columns=["code", "shares", "scale_source"])
    frame = frame.rename(columns={"基金代码": "code", "当前规模(份)": "shares"}).copy()
    if "code" not in frame.columns or "shares" not in frame.columns:
        return pd.DataFrame(columns=["code", "shares", "scale_source"])
    frame["shares"] = frame["shares"].astype(str).str.replace(",", "", regex=False)
    frame["scale_source"] = "szse_shares"
    return frame[["code", "shares", "scale_source"]]


def fetch_etf_daily_bars(code: str) -> pd.DataFrame:
    with _quiet_akshare():
        import akshare as ak

        frame = ak.fund_etf_hist_sina(symbol=to_sina_symbol(code))
    if "date" in frame.columns:
        frame["date"] = frame["date"].astype(str)
    return frame


def to_sina_symbol(code: str) -> str:
    code = normalize_etf_code(code)
    prefix = "sh" if code.startswith("5") else "sz"
    return prefix + code


@contextmanager
def _quiet_akshare():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield

from contextlib import contextmanager
from io import BytesIO
from datetime import date
import warnings

import pandas as pd
warnings.filterwarnings("ignore", message=".*urllib3.*chardet.*")
warnings.filterwarnings("ignore", message="Workbook contains no default style.*")
import requests

from .etf_pool import normalize_etf_code


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

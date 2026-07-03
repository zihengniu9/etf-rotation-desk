import pandas as pd
import warnings

warnings.filterwarnings("ignore", message=".*urllib3.*chardet.*")
import requests


HOT_ETF_URL = "https://eq.10jqka.com.cn/open/api/etf_rank/v1/hot.txt"
HOT_ETF_COLUMNS = ["rank", "code", "name", "market", "heat", "sdate", "stime"]


def fetch_hot_etfs(*, limit: int = 30, timeout: int = 15) -> pd.DataFrame:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://eq.10jqka.com.cn/webpage/etf-ranking-list/index.html",
    }
    try:
        response = requests.get(HOT_ETF_URL, headers=headers, timeout=timeout)
        response.raise_for_status()
        return parse_hot_etf_response(response.json(), limit=limit)
    except Exception:
        return pd.DataFrame(columns=HOT_ETF_COLUMNS)


def parse_hot_etf_response(payload: dict, *, limit: int = 30) -> pd.DataFrame:
    items = payload.get("data", {}).get("list", []) if isinstance(payload, dict) else []
    rows: list[dict] = []
    for index, item in enumerate(items[:limit], start=1):
        code = str(item.get("code", "")).strip()
        rows.append(
            {
                "rank": index,
                "code": code.zfill(6) if code.isdigit() else code,
                "name": item.get("name", ""),
                "market": str(item.get("market", "")),
                "heat": float(item.get("rate", 0) or 0),
                "sdate": str(item.get("sdate", "")),
                "stime": str(item.get("stime", "")),
            }
        )
    return pd.DataFrame(rows, columns=HOT_ETF_COLUMNS)

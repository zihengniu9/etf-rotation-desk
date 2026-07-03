from io import StringIO
import re
import warnings

import pandas as pd

warnings.filterwarnings("ignore", message=".*urllib3.*chardet.*")
import requests


BOARD_URL = "https://q.10jqka.com.cn/thshy/detail/code/{board_code}/page/{page}/"


def parse_board_constituents(html: str) -> pd.DataFrame:
    tables = pd.read_html(StringIO(html))
    for table in tables:
        columns = [str(column) for column in table.columns]
        if "代码" in columns and "名称" in columns:
            frame = table.copy()
            frame.columns = columns
            frame["代码"] = frame["代码"].map(format_stock_code)
            frame["名称"] = frame["名称"].astype(str).str.strip()
            return frame
    raise ValueError("constituent table with columns 代码 and 名称 not found")


def parse_total_pages(html: str) -> int:
    match = re.search(r'<span class="page_info">\s*\d+\s*/\s*(\d+)\s*</span>', html)
    if not match:
        return 1
    return int(match.group(1))


def fetch_board_page(board_code: str, page: int, *, timeout: float = 20.0) -> str:
    url = BOARD_URL.format(board_code=board_code, page=page)
    response = requests.get(
        url,
        timeout=timeout,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": f"https://q.10jqka.com.cn/thshy/detail/code/{board_code}/",
        },
    )
    response.raise_for_status()
    response.encoding = "gbk"
    return response.text


def fetch_board_constituents(board_code: str = "883910", *, timeout: float = 20.0) -> pd.DataFrame:
    first_html = fetch_board_page(board_code, 1, timeout=timeout)
    total_pages = parse_total_pages(first_html)
    frames = [parse_board_constituents(first_html)]
    for page in range(2, total_pages + 1):
        frames.append(parse_board_constituents(fetch_board_page(board_code, page, timeout=timeout)))
    result = pd.concat(frames, ignore_index=True)
    return result.drop_duplicates(subset=["代码"]).reset_index(drop=True)


def format_stock_code(value: object) -> str:
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    digits = re.sub(r"\D", "", text)
    return digits.zfill(6)[-6:]

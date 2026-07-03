from contextlib import contextmanager
import warnings

import pandas as pd


def fetch_daily_bars(
    code: str,
    *,
    start_date: str,
    end_date: str,
    adjust: str = "qfq",
    timeout: float = 20.0,
) -> pd.DataFrame:
    with _quiet_akshare():
        ak = _import_akshare()
        frame = ak.stock_zh_a_hist_tx(
            symbol=to_tx_symbol(code),
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
            timeout=timeout,
        )
    if "date" in frame.columns:
        frame["date"] = frame["date"].astype(str)
    return frame


def fetch_hot_keywords(code: str) -> pd.DataFrame:
    with _quiet_akshare():
        ak = _import_akshare()
        return ak.stock_hot_keyword_em(symbol=to_em_symbol(code))


def fetch_business_description(code: str) -> pd.DataFrame:
    with _quiet_akshare():
        ak = _import_akshare()
        return ak.stock_zyjs_ths(symbol=code)


def to_tx_symbol(code: str) -> str:
    code = str(code).zfill(6)
    return _lower_market_prefix(code) + code


def to_em_symbol(code: str) -> str:
    code = str(code).zfill(6)
    return _upper_market_prefix(code) + code


def _lower_market_prefix(code: str) -> str:
    if code.startswith(("6", "9")):
        return "sh"
    if code.startswith(("4", "8")):
        return "bj"
    return "sz"


def _upper_market_prefix(code: str) -> str:
    return _lower_market_prefix(code).upper()


@contextmanager
def _quiet_akshare():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield


def _import_akshare():
    import akshare as ak

    _disable_akshare_progress()
    return ak


def _disable_akshare_progress() -> None:
    try:
        import akshare.stock_feature.stock_hist_tx as stock_hist_tx

        stock_hist_tx.get_tqdm = lambda enable=True: (lambda iterable, *args, **kwargs: iterable)
    except Exception:
        return

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


RUN_TZ = ZoneInfo("Asia/Hong_Kong")
OUTPUT_COLUMNS = [
    "date",
    "industry",
    "code",
    "turnover",
    "total_turnover",
    "turnover_share",
    "up_count",
    "total_count",
    "return_1d",
    "benchmark_1d",
    "turnover_ratio",
]


def extract_embedded_data(html_path: Path) -> pd.DataFrame:
    text = html_path.read_text(encoding="utf-8")
    marker = "const LIVE_DATA ="
    marker_index = text.find(marker)
    array_index = text.find("[", marker_index + len(marker)) if marker_index >= 0 else -1
    if array_index < 0:
        raise ValueError(f"LIVE_DATA not found in {html_path}")
    try:
        rows, _ = json.JSONDecoder().raw_decode(text[array_index:])
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid LIVE_DATA in {html_path}: {error}") from error
    if not isinstance(rows, list):
        raise ValueError(f"LIVE_DATA must be an array in {html_path}")
    return normalize_rows(pd.DataFrame(rows))


def normalize_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    result = frame.copy()
    for column in OUTPUT_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    result["industry"] = result["industry"].fillna("").astype(str).str.strip()
    for column in OUTPUT_COLUMNS[3:]:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result.dropna(subset=["date"])
    result = result[result["industry"] != ""]
    return result[OUTPUT_COLUMNS].reset_index(drop=True)


def align_turnover_units(snapshot: pd.DataFrame, previous: pd.DataFrame) -> pd.DataFrame:
    """Align live turnover units with the yuan-based historical series."""
    result = snapshot.copy()
    prior = normalize_rows(previous)
    current_total = result["turnover"].sum()
    prior_totals = prior.groupby("date")["turnover"].sum()
    if current_total > 0 and not prior_totals.empty:
        reference_total = float(prior_totals.tail(20).median())
        if reference_total > current_total * 10000:
            result["turnover"] = result["turnover"] * 100_000_000
    return result


def _column(frame: pd.DataFrame, names: tuple[str, ...], fallback_index: int) -> pd.Series:
    for name in names:
        if name in frame.columns:
            return frame[name]
    if fallback_index < len(frame.columns):
        return frame.iloc[:, fallback_index]
    return pd.Series(index=frame.index, dtype=float)


def build_daily_snapshot(summary: pd.DataFrame, as_of: str, previous: pd.DataFrame) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    snapshot = pd.DataFrame(index=summary.index)
    snapshot["date"] = as_of
    snapshot["industry"] = _column(summary, ("板块", "行业", "name"), 1).astype(str).str.strip()
    snapshot["code"] = ""
    snapshot["turnover"] = pd.to_numeric(_column(summary, ("总成交额", "成交额", "turnover"), 4), errors="coerce")
    snapshot = align_turnover_units(snapshot, previous)
    prior = normalize_rows(previous)
    snapshot["up_count"] = pd.to_numeric(_column(summary, ("上涨家数", "上涨家数"), 6), errors="coerce")
    down_count = pd.to_numeric(_column(summary, ("下跌家数", "下跌家数"), 7), errors="coerce")
    snapshot["total_count"] = snapshot["up_count"].fillna(0) + down_count.fillna(0)
    snapshot["return_1d"] = pd.to_numeric(_column(summary, ("涨跌幅", "return_1d"), 2), errors="coerce")
    snapshot["total_turnover"] = snapshot["turnover"].sum()
    if snapshot["total_turnover"].iloc[0] > 0:
        snapshot["turnover_share"] = snapshot["turnover"] / snapshot["total_turnover"].iloc[0] * 100
        snapshot["benchmark_1d"] = (
            (snapshot["return_1d"].fillna(0) * snapshot["turnover"].fillna(0)).sum()
            / snapshot["turnover"].fillna(0).sum()
        )
    else:
        snapshot["turnover_share"] = 0.0
        snapshot["benchmark_1d"] = 0.0

    prior = prior[prior["date"] != as_of]
    history = prior.sort_values("date").groupby("industry", sort=False)["turnover"].tail(20)
    baseline_by_industry = history.groupby(prior.loc[history.index, "industry"]).mean()
    snapshot["turnover_ratio"] = snapshot.apply(
        lambda row: row["turnover"] / baseline_by_industry.get(row["industry"], row["turnover"])
        if baseline_by_industry.get(row["industry"], row["turnover"]) > 0
        else 1.0,
        axis=1,
    )
    return normalize_rows(snapshot)


def merge_snapshot(previous: pd.DataFrame, snapshot: pd.DataFrame, max_days: int = 252) -> pd.DataFrame:
    combined = pd.concat([normalize_rows(previous), normalize_rows(snapshot)], ignore_index=True)
    combined = combined.drop_duplicates(subset=["date", "industry"], keep="last")
    dates = sorted(combined["date"].dropna().unique())
    if len(dates) > max_days:
        combined = combined[combined["date"].isin(dates[-max_days:])]
    return combined.sort_values(["date", "industry"]).reset_index(drop=True).reindex(columns=OUTPUT_COLUMNS)


def fetch_summary() -> pd.DataFrame:
    import akshare as ak

    return ak.stock_board_industry_summary_ths()


def latest_data_date(frame: pd.DataFrame) -> str | None:
    if frame.empty or "date" not in frame.columns:
        return None
    dates = frame["date"].dropna().astype(str)
    return dates.max() if not dates.empty else None


def write_status(
    status_path: Path,
    *,
    attempted_at: str,
    status: str,
    data_as_of: str | None,
    rows: int,
    history_days: int,
    message: str,
    error: str | None = None,
) -> None:
    payload = {
        "attempted_at": attempted_at,
        "status": status,
        "data_as_of": data_as_of,
        "rows": rows,
        "history_days": history_days,
        "message": message,
    }
    if error:
        payload["error"] = error
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_json(output_path: Path, frame: pd.DataFrame, *, updated_at: str) -> None:
    normalized = normalize_rows(frame)
    normalized = normalized.astype(object).where(pd.notna(normalized), None)
    payload = {
        "updated_at": updated_at,
        "data_as_of": latest_data_date(normalized),
        "history_days": int(normalized["date"].nunique()) if not normalized.empty else 0,
        "rows": normalized.to_dict(orient="records"),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh the industry mainline dashboard data.")
    parser.add_argument("--html", default="web/industry_mainline_dashboard.html")
    parser.add_argument("--output", default="outputs/industry_flow.csv")
    parser.add_argument("--json-output", default="outputs/industry_flow.json")
    parser.add_argument("--status-output", default="outputs/industry_update_status.json")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--as-of", default="", help="Completed trading date, YYYY-MM-DD")
    args = parser.parse_args(argv)

    html_path = Path(args.html)
    output_path = Path(args.output)
    json_output_path = Path(args.json_output)
    status_path = Path(args.status_output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    seed = extract_embedded_data(html_path)
    previous = pd.read_csv(output_path) if output_path.exists() else seed
    previous = normalize_rows(previous)
    attempted_at = datetime.now(RUN_TZ).isoformat(timespec="seconds")

    if args.refresh:
        if not __import__("os").environ.get("HTTPS_PROXY"):
            raise RuntimeError("HTTPS_PROXY is not configured; refusing direct network access")
        if args.as_of:
            as_of = date.fromisoformat(args.as_of).isoformat()
        else:
            now = datetime.now(RUN_TZ)
            candidate = now.date()
            if candidate.weekday() >= 5 or now.time() < datetime.strptime("15:30", "%H:%M").time():
                candidate -= timedelta(days=1)
                while candidate.weekday() >= 5:
                    candidate -= timedelta(days=1)
            as_of = candidate.isoformat()
        try:
            snapshot = build_daily_snapshot(fetch_summary(), as_of, previous)
            if snapshot.empty:
                raise ValueError("industry summary returned no usable rows")
            merged = merge_snapshot(previous, snapshot)
            print(f"industry_snapshot={as_of} rows={len(snapshot)} history_days={merged['date'].nunique()}")
            write_status(
                status_path,
                attempted_at=attempted_at,
                status="success",
                data_as_of=latest_data_date(merged),
                rows=len(merged),
                history_days=merged["date"].nunique(),
                message="行业主线数据已成功刷新",
            )
        except Exception as exc:
            merged = previous
            error = f"{type(exc).__name__}: {exc}"
            print(f"industry update stale: {error}")
            write_status(
                status_path,
                attempted_at=attempted_at,
                status="stale",
                data_as_of=latest_data_date(merged),
                rows=len(merged),
                history_days=merged["date"].nunique() if not merged.empty else 0,
                message="在线接口未返回可用数据，沿用上一版行业数据",
                error=error,
            )
    else:
        merged = previous
        print(f"industry seed rows={len(merged)} history_days={merged['date'].nunique()}")
        write_status(
            status_path,
            attempted_at=attempted_at,
            status="seed",
            data_as_of=latest_data_date(merged),
            rows=len(merged),
            history_days=merged["date"].nunique() if not merged.empty else 0,
            message="当前为内置行业数据快照，尚未执行在线刷新",
        )

    merged.to_csv(output_path, index=False, encoding="utf-8-sig")
    write_json(json_output_path, merged, updated_at=attempted_at)
    print(f"wrote {output_path}")
    print(f"wrote {json_output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

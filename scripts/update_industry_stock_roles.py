from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


RUN_TZ = ZoneInfo("Asia/Hong_Kong")
API_URL = "https://openapi.iwencai.com/v1/query2data"


def number(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "")
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def first_value(row: dict[str, Any], names: tuple[str, ...], default: Any = None) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
        for key, value in row.items():
            if str(key).startswith(f"{name}[") and value not in (None, ""):
                return value
    return default


def code_key(value: Any) -> str:
    text = str(value or "").strip().upper()
    if "." in text:
        text = text.split(".", 1)[0]
    return text.zfill(6) if text.isdigit() else text


def industry_names(row: dict[str, Any]) -> list[str]:
    value = first_value(row, ("所属同花顺行业", "所属行业", "行业"), [])
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).replace("；", ";").split(";") if item.strip()]


def normalize_stock_rows(rows: list[dict[str, Any]], industry: str) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        code = code_key(first_value(row, ("股票代码", "代码", "证券代码", "code")))
        name = str(first_value(row, ("股票简称", "名称", "股票名称", "name"), "")).strip()
        if not code or not name or name.upper().startswith("ST"):
            continue
        groups = industry_names(row)
        if groups and industry not in groups and industry not in " ".join(groups):
            continue
        result.append(
            {
                "code": code,
                "name": name,
                "price": number(first_value(row, ("最新价", "现价", "price"))),
                "change": number(first_value(row, ("最新涨跌幅", "涨跌幅", "涨跌幅[最新]", "ratio"))),
                "amount": number(first_value(row, ("成交额", "成交额[最新]", "成交额(元)", "amount"))),
                "turnover_rate": number(first_value(row, ("换手率", "换手率[最新]", "turnover_rate"))),
                "heat": number(first_value(row, ("个股热度", "热度", "热度排名", "heat"))),
            }
        )
    unique: dict[str, dict[str, Any]] = {}
    for row in result:
        unique[row["code"]] = row
    return list(unique.values())


def _relative(values: list[float], value: float, invert: bool = False) -> float:
    if not values:
        return 0.0
    low, high = min(values), max(values)
    score = 1.0 if high == low else (value - low) / (high - low)
    return 1.0 - score if invert else score


def score_roles(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    amounts = [max(0.0, number(row.get("amount"))) for row in rows]
    heats = [max(0.0, number(row.get("heat"))) for row in rows]
    turnovers = [max(0.0, number(row.get("turnover_rate"))) for row in rows]
    amount_logs = [math.log1p(value) for value in amounts]
    heat_logs = [math.log1p(value) for value in heats]
    for row, amount_log, heat_log in zip(rows, amount_logs, heat_logs):
        amount_score = _relative(amount_logs, amount_log)
        heat_score = _relative(heat_logs, heat_log)
        momentum_score = max(0.0, min(1.0, (number(row.get("change")) + 2.0) / 12.0))
        turnover_score = max(0.0, min(1.0, number(row.get("turnover_rate")) / 12.0))
        row["leader_score"] = heat_score * 0.40 + momentum_score * 0.30 + turnover_score * 0.15 + amount_score * 0.15
        row["center_score"] = amount_score * 0.55 + heat_score * 0.15 + momentum_score * 0.15 + turnover_score * 0.15
        row["spread_score"] = momentum_score * 0.40 + turnover_score * 0.25 + heat_score * 0.20 + amount_score * 0.15

    def ranked(key: str, excluded: set[str]) -> dict[str, Any] | None:
        candidates = [row for row in rows if row["code"] not in excluded]
        return max(candidates, key=lambda row: (row[key], row["heat"], row["amount"]), default=None)

    leader = ranked("leader_score", set())
    center = ranked("center_score", {leader["code"]} if leader else set()) or leader
    excluded = {row["code"] for row in (leader, center) if row}
    spread = ranked("spread_score", excluded)

    def present(row: dict[str, Any] | None, role: str) -> dict[str, Any] | None:
        if not row:
            return None
        score_key = {"leader": "leader_score", "center": "center_score", "spread": "spread_score"}.get(role, "leader_score")
        return {
            "role": role,
            "code": row["code"],
            "name": row["name"],
            "price": round(number(row.get("price")), 4),
            "change": round(number(row.get("change")), 2),
            "amount": round(number(row.get("amount")), 2),
            "turnover_rate": round(number(row.get("turnover_rate")), 2),
            "heat": round(number(row.get("heat")), 2),
            "score": round(number(row.get(score_key)) * 100, 1),
        }

    return {
        "leader": present(leader, "leader"),
        "center": present(center, "center"),
        "spread": present(spread, "spread"),
        "rows": [present(row, "member") for row in sorted(rows, key=lambda item: item["heat"], reverse=True)[:12]],
    }


def load_mainline_industries(path: Path, limit: int = 6) -> tuple[str | None, list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows", payload) if isinstance(payload, dict) else payload
    if not rows:
        return None, []
    latest_date = payload.get("data_as_of") if isinstance(payload, dict) else None
    latest_date = latest_date or max(str(row.get("date", "")) for row in rows)
    latest = [row for row in rows if str(row.get("date", "")) == latest_date]
    by_industry: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_industry.setdefault(str(row.get("industry", "")).strip(), []).append(row)
    scored = []
    for row in latest:
        industry = str(row.get("industry", "")).strip()
        if not industry:
            continue
        history = sorted(by_industry.get(industry, []), key=lambda item: str(item.get("date", "")))[-5:]
        persistence = sum(
            number(item.get("turnover_ratio")) >= 1.05 and number(item.get("return_1d")) >= 0
            for item in history
        ) / max(1, len(history))
        breadth = number(row.get("up_count")) / max(1.0, number(row.get("total_count")))
        excess = number(row.get("return_1d")) - number(row.get("benchmark_1d"))
        score = (
            min(1.0, number(row.get("turnover_share")) / 5.0) * 0.25
            + min(1.0, number(row.get("turnover_ratio")) / 2.0) * 0.18
            + breadth * 0.18
            + max(0.0, min(1.0, (excess + 2.0) / 6.0)) * 0.15
            + persistence * 0.24
        )
        scored.append((score, industry))
    return latest_date, [industry for _, industry in sorted(scored, reverse=True)[:limit]]


def query_iwencai(industry: str, limit: int = 80) -> list[dict[str, Any]]:
    api_key = os.environ.get("IWENCAI_API_KEY", "")
    if not api_key:
        return []
    body = json.dumps(
        {
            "query": f"{industry}行业股票同花顺热度排名最新价涨跌幅成交额换手率",
            "page": "1",
            "limit": str(limit),
            "is_cache": "1",
            "expand_index": "true",
        }
    ).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Claw-Call-Type": "normal",
        "X-Claw-Skill-Id": "hithink-market-query",
        "X-Claw-Skill-Version": "1.0.0",
        "X-Claw-Plugin-Id": "none",
        "X-Claw-Plugin-Version": "none",
        "X-Claw-Trace-Id": secrets.token_hex(32),
    }
    request = urllib.request.Request(API_URL, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("datas", []) if isinstance(payload, dict) else []


def query_akshare(industry: str, hot_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    import akshare as ak

    frame = ak.stock_board_industry_cons_em(symbol=industry)
    rows = frame.to_dict(orient="records")
    normalized = normalize_stock_rows(rows, industry)
    for row in normalized:
        row.update(hot_map.get(row["code"], {}))
    return normalized


def load_hot_map() -> dict[str, dict[str, Any]]:
    try:
        import akshare as ak

        rows = ak.stock_hot_rank_em().to_dict(orient="records")
    except Exception:
        return {}
    result = {}
    for row in rows:
        code = code_key(first_value(row, ("代码", "股票代码", "code")))
        if code:
            result[code] = {
                "heat": number(first_value(row, ("热度", "当前热度", "hot"))),
            }
    return result


def load_seed_rows(path: Path | None, industry: str) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("datas", payload.get("rows", payload)) if isinstance(payload, dict) else payload
    return normalize_stock_rows(rows if isinstance(rows, list) else [], industry)


def write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh stock-level roles for industry mainlines.")
    parser.add_argument("--industry-input", default="outputs/industry_flow.json")
    parser.add_argument("--output", default="outputs/industry_stock_roles.json")
    parser.add_argument("--status-output", default="outputs/industry_stock_roles_status.json")
    parser.add_argument("--raw-input", default="")
    args = parser.parse_args(argv)

    output_path = Path(args.output)
    status_path = Path(args.status_output)
    attempted_at = datetime.now(RUN_TZ).isoformat(timespec="seconds")
    data_as_of, industries = load_mainline_industries(Path(args.industry_input))
    roles: dict[str, Any] = {}
    hot_map = {} if os.environ.get("IWENCAI_API_KEY") else load_hot_map()
    errors: list[str] = []
    for industry in industries:
        industry_source = ""
        rows = load_seed_rows(Path(args.raw_input), industry) if args.raw_input else []
        if args.raw_input and not rows:
            continue
        if rows:
            industry_source = "同花顺问财个股热度"
        if not rows:
            try:
                rows = normalize_stock_rows(query_iwencai(industry), industry)
                if rows:
                    industry_source = "同花顺问财个股热度"
            except Exception as exc:
                errors.append(f"{industry}: 问财 {type(exc).__name__}: {exc}")
        if not rows:
            try:
                rows = query_akshare(industry, hot_map)
                if rows:
                    industry_source = "行业成分股行情"
            except Exception as exc:
                errors.append(f"{industry}: AkShare {type(exc).__name__}: {exc}")
        scored = score_roles(rows)
        if scored:
            roles[industry] = {
                **scored,
                "source": industry_source or "行业成分股行情",
                "data_as_of": data_as_of,
            }

    payload = {
        "updated_at": attempted_at,
        "data_as_of": data_as_of,
        "source": "同花顺问财个股热度 + 行业成分股行情",
        "industries": roles,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    status = "success" if roles else "stale"
    write_status(
        status_path,
        {
            "attempted_at": attempted_at,
            "status": status,
            "data_as_of": data_as_of,
            "industries": len(roles),
            "message": "行业主线股票角色已刷新" if roles else "未取得行业成分股数据，页面保留无角色状态",
            "source": "同花顺问财个股热度 + 行业成分股行情",
            "errors": errors[:10],
        },
    )
    print(f"industry_stock_roles={len(roles)} data_as_of={data_as_of}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

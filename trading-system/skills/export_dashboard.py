from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = SYSTEM_DIR / "database.sqlite"
DEFAULT_CONFIG_PATH = SYSTEM_DIR / "config.json"
DEFAULT_OUTPUT_PATH = SYSTEM_DIR.parent / "dashboard" / "data" / "dashboard-data.json"


def export_dashboard_snapshot(
    db_path: str,
    output_path: str,
    config_path: str | None = None,
    decisions_limit: int = 400,
    trades_limit: int = 250,
    events_limit: int = 120,
):
    db_file = Path(db_path)
    if not db_file.exists():
        raise FileNotFoundError(f"Database not found: {db_file}")

    config = _load_json_file(config_path) if config_path else {}
    assets = _extract_assets_from_config(config)
    generated_at = _utc_now()
    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    try:
        market_snapshot = _fetch_market_snapshot(conn, assets)
        last_prices = _derive_last_prices(conn, assets, market_snapshot)

        agents = _fetch_agents(conn)
        portfolios = _fetch_portfolios(conn)
        positions_by_agent = _fetch_positions(conn, last_prices)

        decisions_recent = _fetch_recent_decisions(conn, limit=decisions_limit)
        trades_recent = _fetch_recent_trades(conn, limit=trades_limit)
        events_recent = _fetch_recent_events(conn, limit=events_limit)

        decisions_all = _fetch_action_counts(conn, "decisions")
        decisions_24h = _fetch_action_counts(conn, "decisions", since=cutoff_24h)
        trades_all = _fetch_trade_stats(conn)
        trades_24h = _fetch_trade_stats(conn, since=cutoff_24h)

        agent_payload = _build_agent_payload(
            agents=agents,
            portfolios=portfolios,
            positions_by_agent=positions_by_agent,
            decisions_all=decisions_all,
            decisions_24h=decisions_24h,
            trades_all=trades_all,
            trades_24h=trades_24h,
        )

        summary = _build_summary(
            agents=agent_payload,
            decisions_recent=decisions_recent,
            trades_recent=trades_recent,
            decisions_24h=decisions_24h,
            trades_24h=trades_24h,
        )

        payload = {
            "generated_at": generated_at,
            "system": {
                "name": config.get("system", {}).get("name", "cryptoMaster Orchestrator"),
                "mode": config.get("system", {}).get("mode", "dry_run"),
                "base_currency": config.get("system", {}).get("base_currency", "EUR"),
                "supported_assets": assets,
            },
            "summary": summary,
            "market": market_snapshot,
            "agents": agent_payload,
            "recent_decisions": decisions_recent,
            "recent_trades": trades_recent,
            "recent_events": events_recent,
            "score_series": _build_score_series(decisions_recent, assets),
        }
    finally:
        conn.close()

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return str(out_file)


def main():
    parser = argparse.ArgumentParser(
        description="Export SQLite trading state into JSON for static dashboards."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to SQLite database")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config.json")
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUTPUT_PATH),
        help="Output path for dashboard JSON payload",
    )
    parser.add_argument(
        "--decisions-limit",
        type=int,
        default=400,
        help="Maximum number of recent decisions exported",
    )
    parser.add_argument(
        "--trades-limit",
        type=int,
        default=250,
        help="Maximum number of recent trades exported",
    )
    parser.add_argument(
        "--events-limit",
        type=int,
        default=120,
        help="Maximum number of recent events exported",
    )
    args = parser.parse_args()

    output_file = export_dashboard_snapshot(
        db_path=str(_resolve_path(args.db)),
        output_path=str(_resolve_path(args.out)),
        config_path=str(_resolve_path(args.config)),
        decisions_limit=max(50, args.decisions_limit),
        trades_limit=max(50, args.trades_limit),
        events_limit=max(20, args.events_limit),
    )
    print(f"Dashboard export written to: {output_file}")


def _build_agent_payload(
    agents,
    portfolios,
    positions_by_agent,
    decisions_all,
    decisions_24h,
    trades_all,
    trades_24h,
):
    out = []
    for agent in agents:
        agent_id = agent["id"]
        portfolio = portfolios.get(agent_id, {"cash_balance": 0.0, "initial_balance": 0.0})
        cash_balance = float(portfolio["cash_balance"])
        initial_balance = float(portfolio["initial_balance"])
        positions = positions_by_agent.get(agent_id, [])
        positions_value = sum(float(position["market_value_eur"]) for position in positions)
        equity = cash_balance + positions_value
        pnl_abs = equity - initial_balance
        pnl_pct = (pnl_abs / initial_balance) if initial_balance else 0.0

        position_weight_denominator = equity if equity > 0 else 1.0
        allocations = [
            {
                **position,
                "weight_pct": round(
                    (float(position["market_value_eur"]) / position_weight_denominator) * 100.0,
                    4,
                ),
            }
            for position in positions
        ]
        allocations.sort(key=lambda row: float(row["market_value_eur"]), reverse=True)

        trade_info_all = trades_all.get(agent_id, {"count": 0, "fees": 0.0})
        trade_info_24h = trades_24h.get(agent_id, {"count": 0, "fees": 0.0})

        out.append(
            {
                "id": agent_id,
                "name": agent["name"],
                "risk_profile": agent["risk_profile"],
                "assets": agent["assets"],
                "timeframes": agent["timeframes"],
                "cash_balance": round(cash_balance, 8),
                "initial_balance": round(initial_balance, 8),
                "positions_value_eur": round(positions_value, 8),
                "equity": round(equity, 8),
                "pnl_abs": round(pnl_abs, 8),
                "pnl_pct": round(pnl_pct, 6),
                "positions": allocations,
                "decisions": {
                    "all_time": decisions_all.get(agent_id, _empty_action_count()),
                    "last_24h": decisions_24h.get(agent_id, _empty_action_count()),
                },
                "trades": {
                    "all_time_count": int(trade_info_all["count"]),
                    "all_time_fees_eur": round(float(trade_info_all["fees"]), 8),
                    "last_24h_count": int(trade_info_24h["count"]),
                    "last_24h_fees_eur": round(float(trade_info_24h["fees"]), 8),
                },
            }
        )
    return out


def _build_summary(agents, decisions_recent, trades_recent, decisions_24h, trades_24h):
    total_initial = sum(float(agent["initial_balance"]) for agent in agents)
    total_equity = sum(float(agent["equity"]) for agent in agents)
    total_cash = sum(float(agent["cash_balance"]) for agent in agents)
    total_positions = sum(float(agent["positions_value_eur"]) for agent in agents)
    total_fees = sum(float(agent["trades"]["all_time_fees_eur"]) for agent in agents)
    pnl_abs = total_equity - total_initial
    pnl_pct = (pnl_abs / total_initial) if total_initial else 0.0

    decision_24h_total = sum(
        stats["total"] for stats in decisions_24h.values()
    )
    trades_24h_total = sum(
        int(stats["count"]) for stats in trades_24h.values()
    )

    return {
        "agent_count": len(agents),
        "decisions_count": len(decisions_recent),
        "trades_count": len(trades_recent),
        "decisions_last_24h": int(decision_24h_total),
        "trades_last_24h": int(trades_24h_total),
        "total_initial_balance": round(total_initial, 8),
        "total_equity": round(total_equity, 8),
        "total_cash_balance": round(total_cash, 8),
        "total_positions_value": round(total_positions, 8),
        "total_fees_eur": round(total_fees, 8),
        "pnl_abs": round(pnl_abs, 8),
        "pnl_pct": round(pnl_pct, 6),
    }


def _fetch_agents(conn):
    rows = conn.execute(
        """
        SELECT id, name, risk_profile, assets, timeframes
        FROM agents
        ORDER BY id
        """
    ).fetchall()
    out = []
    for row in rows:
        out.append(
            {
                "id": row["id"],
                "name": row["name"],
                "risk_profile": row["risk_profile"],
                "assets": _safe_json_loads(row["assets"], []),
                "timeframes": _safe_json_loads(row["timeframes"], []),
            }
        )
    return out


def _fetch_portfolios(conn):
    rows = conn.execute(
        """
        SELECT agent_id, cash_balance, initial_balance
        FROM portfolios
        """
    ).fetchall()
    out = {}
    for row in rows:
        out[row["agent_id"]] = {
            "cash_balance": float(row["cash_balance"]),
            "initial_balance": float(row["initial_balance"]),
        }
    return out


def _fetch_positions(conn, last_prices):
    rows = conn.execute(
        """
        SELECT agent_id, asset, quantity, avg_price, updated_at
        FROM positions
        ORDER BY agent_id, asset
        """
    ).fetchall()
    out = defaultdict(list)
    for row in rows:
        market_price = float(last_prices.get(row["asset"], row["avg_price"]))
        market_value = float(row["quantity"]) * market_price
        out[row["agent_id"]].append(
            {
                "asset": row["asset"],
                "quantity": round(float(row["quantity"]), 10),
                "avg_price": round(float(row["avg_price"]), 10),
                "market_price": round(market_price, 10),
                "market_value_eur": round(market_value, 8),
                "updated_at": row["updated_at"],
            }
        )
    return out


def _fetch_recent_decisions(conn, limit: int):
    rows = conn.execute(
        """
        SELECT id, agent_id, asset, timeframe, regime, score, action, rationale, created_at
        FROM decisions
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    out = []
    for row in rows:
        out.append(
            {
                "id": int(row["id"]),
                "agent_id": row["agent_id"],
                "asset": row["asset"],
                "timeframe": row["timeframe"],
                "regime": row["regime"],
                "score": round(float(row["score"]), 4),
                "action": row["action"],
                "rationale": _safe_json_loads(row["rationale"], {}),
                "created_at": row["created_at"],
            }
        )
    return out


def _fetch_recent_trades(conn, limit: int):
    rows = conn.execute(
        """
        SELECT id, agent_id, asset, side, quantity, price, notional, fee, reason, dry_run, created_at
        FROM trades
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    out = []
    for row in rows:
        out.append(
            {
                "id": int(row["id"]),
                "agent_id": row["agent_id"],
                "asset": row["asset"],
                "side": row["side"],
                "quantity": round(float(row["quantity"]), 10),
                "price": round(float(row["price"]), 10),
                "notional_eur": round(float(row["notional"]), 8),
                "fee_eur": round(float(row["fee"]), 8),
                "reason": row["reason"],
                "dry_run": bool(int(row["dry_run"])),
                "created_at": row["created_at"],
            }
        )
    return out


def _fetch_recent_events(conn, limit: int):
    rows = conn.execute(
        """
        SELECT id, event_type, payload, created_at
        FROM events
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    out = []
    for row in rows:
        out.append(
            {
                "id": int(row["id"]),
                "event_type": row["event_type"],
                "payload": _safe_json_loads(row["payload"], row["payload"]),
                "created_at": row["created_at"],
            }
        )
    return out


def _fetch_action_counts(conn, table_name: str, since: str | None = None):
    if table_name not in {"decisions"}:
        raise ValueError(f"Unsupported table for action count: {table_name}")

    query = "SELECT agent_id, action, COUNT(*) as count FROM decisions"
    params = []
    if since:
        query += " WHERE created_at >= ?"
        params.append(since)
    query += " GROUP BY agent_id, action"

    rows = conn.execute(query, tuple(params)).fetchall()
    out = defaultdict(_empty_action_count)
    for row in rows:
        bucket = out[row["agent_id"]]
        action = row["action"].upper()
        if action not in bucket:
            bucket[action] = 0
        bucket[action] += int(row["count"])
        bucket["total"] += int(row["count"])
    return dict(out)


def _fetch_trade_stats(conn, since: str | None = None):
    query = "SELECT agent_id, COUNT(*) AS count, COALESCE(SUM(fee), 0) AS fees FROM trades"
    params = []
    if since:
        query += " WHERE created_at >= ?"
        params.append(since)
    query += " GROUP BY agent_id"
    rows = conn.execute(query, tuple(params)).fetchall()
    out = {}
    for row in rows:
        out[row["agent_id"]] = {
            "count": int(row["count"]),
            "fees": float(row["fees"]),
        }
    return out


def _fetch_market_snapshot(conn, assets):
    row = conn.execute(
        """
        SELECT payload
        FROM events
        WHERE event_type = 'cycle_summary'
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    if row:
        payload = _safe_json_loads(row["payload"], {})
        snapshot = payload.get("market_snapshot")
        if isinstance(snapshot, dict) and snapshot:
            out = []
            for asset in assets:
                details = snapshot.get(asset, {})
                out.append(
                    {
                        "asset": asset,
                        "last_price": float(details.get("last_price", 0.0)),
                        "price_change_pct_24h": float(details.get("price_change_pct_24h", 0.0)),
                        "quote_volume_24h": float(details.get("quote_volume_24h", 0.0)),
                    }
                )
            return out

    # Fallback from latest trades if no cycle summary exists yet.
    out = []
    for asset in assets:
        trade_row = conn.execute(
            """
            SELECT price
            FROM trades
            WHERE asset = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (asset,),
        ).fetchone()
        out.append(
            {
                "asset": asset,
                "last_price": float(trade_row["price"]) if trade_row else 0.0,
                "price_change_pct_24h": 0.0,
                "quote_volume_24h": 0.0,
            }
        )
    return out


def _derive_last_prices(conn, assets, market_snapshot):
    out = {item["asset"]: float(item["last_price"]) for item in market_snapshot if item["last_price"] > 0}
    for asset in assets:
        if asset in out:
            continue
        row = conn.execute(
            """
            SELECT price
            FROM trades
            WHERE asset = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (asset,),
        ).fetchone()
        if row:
            out[asset] = float(row["price"])
    return out


def _build_score_series(decisions_recent, assets):
    series = {asset: [] for asset in assets}
    ordered = list(reversed(decisions_recent))
    for row in ordered:
        asset = row["asset"]
        if asset not in series:
            continue
        series[asset].append(
            {
                "time": row["created_at"],
                "score": float(row["score"]),
                "action": row["action"],
            }
        )
    for asset in assets:
        if len(series[asset]) > 80:
            series[asset] = series[asset][-80:]
    return series


def _extract_assets_from_config(config):
    assets = config.get("system", {}).get("supported_assets", [])
    if not isinstance(assets, list):
        return []
    return [str(asset).upper() for asset in assets]


def _load_json_file(path: str | None):
    if not path:
        return {}
    file = Path(path)
    if not file.exists():
        return {}
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _safe_json_loads(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _empty_action_count():
    return {"BUY": 0, "SELL": 0, "HOLD": 0, "total": 0}


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _resolve_path(path_str: str):
    path = Path(path_str).expanduser()
    if path.is_absolute():
        return path
    return path.resolve()


if __name__ == "__main__":
    main()

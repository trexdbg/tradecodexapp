from __future__ import annotations

import argparse
import json
import sqlite3
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = SYSTEM_DIR / "database.sqlite"
DEFAULT_CONFIG_PATH = SYSTEM_DIR / "config.json"
DEFAULT_OUTPUT_PATH = SYSTEM_DIR.parent / "dashboard" / "data" / "dashboard-data.json"
DEFAULT_USD_TO_EUR_RATE = 0.92


def export_dashboard_snapshot(
    db_path: str,
    output_path: str,
    config_path: str | None = None,
    decisions_limit: int = 400,
    trades_limit: int = 250,
    events_limit: int = 120,
    lookback_days: int = 3,
):
    db_file = Path(db_path)
    if not db_file.exists():
        raise FileNotFoundError(f"Database not found: {db_file}")

    config = _load_json_file(config_path) if config_path else {}
    agent_config_by_id = _build_agent_config_index(config)
    base_currency = str(config.get("system", {}).get("base_currency", "EUR")).upper()
    now_utc = datetime.now(timezone.utc)
    generated_at = now_utc.isoformat()
    lookback_days = max(1, int(lookback_days))
    cutoff_24h = (now_utc - timedelta(hours=24)).isoformat()
    cutoff_recent = (now_utc - timedelta(days=lookback_days)).isoformat()

    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    try:
        assets = _extract_assets(conn, config)
        market_snapshot = _fetch_market_snapshot(conn, assets, base_currency=base_currency)
        last_prices = _derive_last_prices(conn, assets, market_snapshot)

        agents = _fetch_agents(conn)
        portfolios = _fetch_portfolios(conn)
        positions_by_agent = _fetch_positions(conn, last_prices)

        realized_pnl_by_trade_id = _compute_realized_pnl_by_trade_id(conn)
        decisions_recent = _fetch_recent_decisions(conn, limit=decisions_limit, since=cutoff_recent)
        trades_recent = _fetch_recent_trades(
            conn,
            limit=trades_limit,
            since=cutoff_recent,
            realized_pnl_by_trade_id=realized_pnl_by_trade_id,
        )
        events_recent = _fetch_recent_events(conn, limit=events_limit, since=cutoff_recent)

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
            agent_config_by_id=agent_config_by_id,
        )

        summary = _build_summary(
            agents=agent_payload,
            decisions_recent=decisions_recent,
            trades_recent=trades_recent,
            decisions_24h=decisions_24h,
            trades_24h=trades_24h,
            lookback_days=lookback_days,
        )
        news_and_sentiment = _extract_news_and_sentiment(conn)

        payload = {
            "generated_at": generated_at,
            "system": {
                "name": config.get("system", {}).get("name", "cryptoMaster Orchestrator"),
                "mode": config.get("system", {}).get("mode", "dry_run"),
                "base_currency": base_currency,
            "supported_assets": assets,
        },
        "summary": summary,
        "market": market_snapshot,
        "agents": agent_payload,
        "recent_decisions": decisions_recent,
        "recent_trades": trades_recent,
            "recent_events": events_recent,
            "score_series": _build_score_series(decisions_recent, assets),
            "market_history": _build_market_history(conn, assets),
            "news_feed": news_and_sentiment.get("news_feed", []),
            "sentiment": news_and_sentiment.get("sentiment", {}),
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
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=3,
        help="Maximum age in days for recent decisions/trades/events",
    )
    args = parser.parse_args()

    output_file = export_dashboard_snapshot(
        db_path=str(_resolve_path(args.db)),
        output_path=str(_resolve_path(args.out)),
        config_path=str(_resolve_path(args.config)),
        decisions_limit=max(50, args.decisions_limit),
        trades_limit=max(50, args.trades_limit),
        events_limit=max(20, args.events_limit),
        lookback_days=max(1, args.lookback_days),
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
    agent_config_by_id,
):
    out = []
    for agent in agents:
        agent_id = agent["id"]
        agent_config = agent_config_by_id.get(agent_id, {})
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

        trade_info_all = trades_all.get(agent_id, {"count": 0, "fees": 0.0, "last_trade_at": None})
        trade_info_24h = trades_24h.get(agent_id, {"count": 0, "fees": 0.0, "last_trade_at": None})
        decision_owner_note = _normalize_optional_text(
            agent_config.get("decision_owner_note") or agent_config.get("ownership_note")
        )
        philosophy = _build_agent_philosophy(
            agent_config=agent_config,
            risk_profile=agent["risk_profile"],
            assets=agent["assets"],
            timeframes=agent["timeframes"],
        )

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
                "philosophy": philosophy,
                "decision_owner_note": decision_owner_note,
                "allow_short": bool(agent_config.get("allow_short", False)),
                "managed_by": _normalize_optional_text(agent_config.get("managed_by")),
                "decision_engine": _normalize_optional_text(agent_config.get("decision_engine")),
                "exchange": _normalize_optional_text(agent_config.get("exchange")),
                "positions": allocations,
                "decisions": {
                    "all_time": decisions_all.get(agent_id, _empty_action_count()),
                    "last_24h": decisions_24h.get(agent_id, _empty_action_count()),
                },
                "trades": {
                    "all_time_count": int(trade_info_all["count"]),
                    "all_time_fees_eur": round(float(trade_info_all["fees"]), 8),
                    "last_trade_at": trade_info_all.get("last_trade_at"),
                    "last_24h_count": int(trade_info_24h["count"]),
                    "last_24h_fees_eur": round(float(trade_info_24h["fees"]), 8),
                },
            }
        )
    return out


def _build_agent_config_index(config):
    agents = config.get("agents", [])
    if not isinstance(agents, list):
        return {}

    out = {}
    for entry in agents:
        if not isinstance(entry, dict):
            continue
        agent_id = str(entry.get("id", "")).strip()
        if not agent_id:
            continue
        out[agent_id] = entry
    return out


def _build_agent_philosophy(agent_config, risk_profile: str, assets, timeframes):
    explicit = _normalize_optional_text(
        agent_config.get("philosophy")
        or agent_config.get("decision_owner_note")
        or agent_config.get("ownership_note")
    )
    if explicit:
        return explicit

    risk = str(risk_profile or "balanced").lower()
    assets_label = ", ".join(str(asset).upper() for asset in (assets or []) if str(asset).strip()) or "multi-assets"
    tf_label = ", ".join(str(tf) for tf in (timeframes or []) if str(tf).strip()) or "multi-timeframes"
    strategies = [
        str(name).replace("_", " ")
        for name in (agent_config.get("strategies", []) or [])
        if str(name).strip()
    ]

    style_by_risk = {
        "aggressive": "Execution rapide avec recherche d opportunites directionnelles.",
        "defensive": "Priorite a la protection du capital et au controle du drawdown.",
        "balanced": "Approche equilibree entre momentum, reversion et gestion du risque.",
    }
    style = style_by_risk.get(risk, style_by_risk["balanced"])
    strategy_label = (
        f"Strategies principales: {', '.join(strategies[:3])}."
        if strategies
        else "Allocation adaptive selon le regime de marche."
    )
    side_label = "Mode long/short actif." if bool(agent_config.get("allow_short", False)) else "Mode long only."
    return f"Univers {assets_label} sur {tf_label}. {style} {side_label} {strategy_label}"


def _normalize_optional_text(value):
    text = str(value or "").strip()
    return text or None


def _build_summary(agents, decisions_recent, trades_recent, decisions_24h, trades_24h, lookback_days: int):
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
        "lookback_days": int(lookback_days),
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


def _fetch_recent_decisions(conn, limit: int, since: str | None = None):
    query = """
        SELECT id, agent_id, asset, timeframe, regime, score, action, rationale, created_at
        FROM decisions
    """
    params = []
    if since:
        query += " WHERE created_at >= ?"
        params.append(since)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, tuple(params)).fetchall()
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


def _fetch_recent_trades(
    conn,
    limit: int,
    since: str | None = None,
    realized_pnl_by_trade_id: dict[int, float] | None = None,
):
    query = """
        SELECT id, agent_id, asset, side, quantity, price, notional, fee, reason, dry_run, created_at
        FROM trades
    """
    params = []
    if since:
        query += " WHERE created_at >= ?"
        params.append(since)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, tuple(params)).fetchall()
    realized_pnl_by_trade_id = realized_pnl_by_trade_id or {}
    out = []
    for row in rows:
        trade_id = int(row["id"])
        realized_pnl = None
        if trade_id in realized_pnl_by_trade_id:
            realized_pnl = round(float(realized_pnl_by_trade_id.get(trade_id, 0.0)), 8)
        out.append(
            {
                "id": trade_id,
                "agent_id": row["agent_id"],
                "asset": row["asset"],
                "side": row["side"],
                "quantity": round(float(row["quantity"]), 10),
                "price": round(float(row["price"]), 10),
                "notional_eur": round(float(row["notional"]), 8),
                "fee_eur": round(float(row["fee"]), 8),
                "realized_pnl_eur": realized_pnl,
                "reason": row["reason"],
                "dry_run": bool(int(row["dry_run"])),
                "created_at": row["created_at"],
            }
        )
    return out


def _compute_realized_pnl_by_trade_id(conn):
    rows = conn.execute(
        """
        SELECT id, agent_id, asset, side, quantity, price, fee
        FROM trades
        ORDER BY id ASC
        """
    ).fetchall()

    lots_by_key = defaultdict(list)
    realized_pnl_by_trade_id = {}
    eps = 1e-10

    for row in rows:
        trade_id = int(row["id"])
        agent_id = str(row["agent_id"] or "")
        asset = str(row["asset"] or "").upper()
        side = str(row["side"] or "").upper()
        quantity = float(row["quantity"] or 0.0)
        price = float(row["price"] or 0.0)
        fee = float(row["fee"] or 0.0)

        if not agent_id or not asset or quantity <= 0.0 or price <= 0.0:
            continue

        key = (agent_id, asset)
        lots = lots_by_key[key]
        remaining_to_close = quantity
        fee_per_unit = fee / quantity
        realized_pnl = 0.0
        matched_any = False

        if side == "BUY":
            # BUY closes existing shorts first, then opens/increases a long lot.
            while remaining_to_close > eps and lots and lots[0]["side"] == "SHORT":
                lot = lots[0]
                matched_qty = min(float(lot["remaining"]), remaining_to_close)
                entry_fee = matched_qty * float(lot["entry_fee_per_unit"])
                exit_fee = matched_qty * fee_per_unit
                realized_pnl += (float(lot["entry_price"]) - price) * matched_qty - entry_fee - exit_fee

                lot["remaining"] = float(lot["remaining"]) - matched_qty
                remaining_to_close -= matched_qty
                matched_any = True
                if float(lot["remaining"]) <= eps:
                    lots.pop(0)

            if remaining_to_close > eps:
                lots.append(
                    {
                        "side": "LONG",
                        "remaining": remaining_to_close,
                        "entry_price": price,
                        "entry_fee_per_unit": fee_per_unit,
                    }
                )
        elif side == "SELL":
            # SELL closes existing longs first, then opens/increases a short lot.
            while remaining_to_close > eps and lots and lots[0]["side"] == "LONG":
                lot = lots[0]
                matched_qty = min(float(lot["remaining"]), remaining_to_close)
                entry_fee = matched_qty * float(lot["entry_fee_per_unit"])
                exit_fee = matched_qty * fee_per_unit
                realized_pnl += (price - float(lot["entry_price"])) * matched_qty - entry_fee - exit_fee

                lot["remaining"] = float(lot["remaining"]) - matched_qty
                remaining_to_close -= matched_qty
                matched_any = True
                if float(lot["remaining"]) <= eps:
                    lots.pop(0)

            if remaining_to_close > eps:
                lots.append(
                    {
                        "side": "SHORT",
                        "remaining": remaining_to_close,
                        "entry_price": price,
                        "entry_fee_per_unit": fee_per_unit,
                    }
                )
        else:
            continue

        if matched_any:
            realized_pnl_by_trade_id[trade_id] = round(realized_pnl, 8)

    return realized_pnl_by_trade_id


def _fetch_recent_events(conn, limit: int, since: str | None = None):
    query = """
        SELECT id, event_type, payload, created_at
        FROM events
    """
    params = []
    if since:
        query += " WHERE created_at >= ?"
        params.append(since)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, tuple(params)).fetchall()
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
    query = """
        SELECT
            agent_id,
            COUNT(*) AS count,
            COALESCE(SUM(fee), 0) AS fees,
            MAX(created_at) AS last_trade_at
        FROM trades
    """
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
            "last_trade_at": row["last_trade_at"],
        }
    return out


def _fetch_market_snapshot(conn, assets, base_currency: str = "EUR"):
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
        data_quality = payload.get("data_quality", {})
        snapshot_currency = str(data_quality.get("market_currency", "USD")).upper()
        usd_to_eur_rate = float(data_quality.get("usd_to_eur_rate", 0.0) or 0.0)
        needs_usd_to_eur = base_currency == "EUR" and snapshot_currency != "EUR"
        if needs_usd_to_eur and usd_to_eur_rate <= 0:
            usd_to_eur_rate = _fetch_usd_to_eur_rate()
        if isinstance(snapshot, dict) and snapshot:
            out = []
            for asset in assets:
                details = snapshot.get(asset, {})
                last_price = float(details.get("last_price", 0.0))
                quote_volume = float(details.get("quote_volume_24h", 0.0))
                if needs_usd_to_eur:
                    last_price *= usd_to_eur_rate
                    quote_volume *= usd_to_eur_rate
                out.append(
                    {
                        "asset": asset,
                        "last_price": last_price,
                        "price_change_pct_24h": float(details.get("price_change_pct_24h", 0.0)),
                        "quote_volume_24h": quote_volume,
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


def _http_get_json(url: str, timeout: int = 8):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "cryptoMaster/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_usd_to_eur_rate(timeout: int = 8):
    try:
        data = _http_get_json("https://api.frankfurter.app/latest?from=USD&to=EUR", timeout=timeout)
        rate = float(data.get("rates", {}).get("EUR", 0.0))
        if rate > 0:
            return rate
    except Exception:
        pass

    try:
        data = _http_get_json("https://api.coinbase.com/v2/exchange-rates?currency=USD", timeout=timeout)
        rate = float(data.get("data", {}).get("rates", {}).get("EUR", 0.0))
        if rate > 0:
            return rate
    except Exception:
        pass

    try:
        data = _http_get_json("https://api.binance.com/api/v3/ticker/price?symbol=EURUSDT", timeout=timeout)
        eur_usdt = float(data.get("price", 0.0))
        if eur_usdt > 0:
            return 1.0 / eur_usdt
    except Exception:
        pass

    return DEFAULT_USD_TO_EUR_RATE


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


def _build_market_history(conn, assets):
    if not assets:
        return {}

    rows = conn.execute(
        """
        SELECT payload
        FROM events
        WHERE event_type = 'cycle_summary'
        ORDER BY id DESC
        LIMIT 720
        """
    ).fetchall()
    history = {asset: [] for asset in assets}
    latest_ts = 0
    for row in rows:
        payload = _safe_json_loads(row["payload"], {})
        ts_str = payload.get("timestamp") or payload.get("created_at")
        parsed_ts = _safe_parse_timestamp(ts_str)
        if not parsed_ts:
            continue
        timestamp_iso = parsed_ts.isoformat()
        latest_ts = max(latest_ts, parsed_ts.timestamp())
        snapshot = payload.get("market_snapshot") or {}
        for asset in assets:
            details = snapshot.get(asset)
            if not isinstance(details, dict):
                continue
            price = details.get("last_price")
            if price is None:
                continue
            history[asset].append(
                {
                    "time": timestamp_iso,
                    "ts": parsed_ts.timestamp(),
                    "price": float(price),
                }
            )

    if latest_ts <= 0:
        return {}

    # ensure ascending order and trim
    for asset in assets:
        points = sorted(history[asset], key=lambda entry: entry["ts"])
        history[asset] = points[-240:]

    now_ts = latest_ts
    windows = {"daily": timedelta(days=1), "weekly": timedelta(days=7), "monthly": timedelta(days=30)}
    market_history = {}
    for label, window in windows.items():
        cutoff = now_ts - window.total_seconds()
        section = []
        for asset, points in history.items():
            filtered = [pt for pt in points if pt["ts"] >= cutoff]
            if not filtered:
                continue
            start_price = filtered[0]["price"]
            end_price = filtered[-1]["price"]
            change_pct = ((end_price - start_price) / start_price) if start_price else 0
            section.append(
                {
                    "asset": asset,
                    "series": [{"time": pt["time"], "price": pt["price"]} for pt in filtered],
                    "change_pct": change_pct,
                    "start_price": start_price,
                    "end_price": end_price,
                }
            )
        if section:
            market_history[label] = section
    return market_history


def _safe_parse_timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _extract_assets_from_config(config):
    assets = config.get("system", {}).get("supported_assets", [])
    if not isinstance(assets, list):
        return []
    return [str(asset).upper() for asset in assets]


def _extract_assets(conn, config):
    latest_summary = conn.execute(
        """
        SELECT payload
        FROM events
        WHERE event_type = 'cycle_summary'
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    if latest_summary:
        payload = _safe_json_loads(latest_summary["payload"], {})
        snapshot = payload.get("market_snapshot", {})
        if isinstance(snapshot, dict):
            assets = [str(asset).upper() for asset in snapshot.keys() if str(asset).strip()]
            if assets:
                return assets

    rotation = conn.execute(
        """
        SELECT payload
        FROM events
        WHERE event_type = 'top_pairs_rotation'
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    if rotation:
        payload = _safe_json_loads(rotation["payload"], {})
        assets = payload.get("assets", [])
        if isinstance(assets, list) and assets:
            return [str(asset).upper() for asset in assets if str(asset).strip()]

    return _extract_assets_from_config(config)


def _extract_news_and_sentiment(conn):
    row = conn.execute(
        """
        SELECT payload
        FROM events
        WHERE event_type = 'cycle_summary'
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        return {"news_feed": [], "sentiment": {}}

    payload = _safe_json_loads(row["payload"], {})
    data_quality = payload.get("data_quality", {}) if isinstance(payload, dict) else {}
    news_feed = data_quality.get("news_items", [])
    if not isinstance(news_feed, list):
        news_feed = []

    sentiment = {
        "score_by_asset": data_quality.get("sentiment_scores", {}),
        "mentions_by_asset": data_quality.get("sentiment_mentions", {}),
        "fear_greed_10_by_asset": data_quality.get("fear_greed_score_10_by_asset", {}),
        "fear_greed_10_overall": float(data_quality.get("fear_greed_score_10_overall", 5.0) or 5.0),
        "news_count": int(data_quality.get("news_count", len(news_feed))),
    }
    return {
        "news_feed": news_feed,
        "sentiment": sentiment,
    }


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

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS agents (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        risk_profile TEXT NOT NULL,
        assets TEXT NOT NULL,
        timeframes TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS portfolios (
        agent_id TEXT PRIMARY KEY,
        cash_balance REAL NOT NULL,
        initial_balance REAL NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(agent_id) REFERENCES agents(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id TEXT NOT NULL,
        asset TEXT NOT NULL,
        quantity REAL NOT NULL,
        avg_price REAL NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(agent_id, asset),
        FOREIGN KEY(agent_id) REFERENCES agents(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id TEXT NOT NULL,
        asset TEXT NOT NULL,
        side TEXT NOT NULL,
        quantity REAL NOT NULL,
        price REAL NOT NULL,
        notional REAL NOT NULL,
        fee REAL NOT NULL,
        reason TEXT NOT NULL,
        dry_run INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(agent_id) REFERENCES agents(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id TEXT NOT NULL,
        asset TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        regime TEXT NOT NULL,
        score REAL NOT NULL,
        action TEXT NOT NULL,
        rationale TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(agent_id) REFERENCES agents(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL,
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_trades_agent_created ON trades(agent_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_decisions_agent_created ON decisions(agent_id, created_at)",
]


def initialize_database(db_path: str, agents, starting_capital: float = 100.0):
    now = _utc_now()
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        for statement in SCHEMA_STATEMENTS:
            cursor.execute(statement)

        for agent in agents:
            cursor.execute(
                """
                INSERT INTO agents (
                    id, name, risk_profile, assets, timeframes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    risk_profile = excluded.risk_profile,
                    assets = excluded.assets,
                    timeframes = excluded.timeframes,
                    updated_at = excluded.updated_at
                """,
                (
                    agent["id"],
                    agent["name"],
                    agent.get("risk_profile", "balanced"),
                    json.dumps(agent.get("assets", []), ensure_ascii=True),
                    json.dumps(agent.get("timeframes", []), ensure_ascii=True),
                    now,
                    now,
                ),
            )
            cursor.execute(
                """
                INSERT OR IGNORE INTO portfolios (agent_id, cash_balance, initial_balance, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (agent["id"], starting_capital, starting_capital, now),
            )

        conn.commit()
    finally:
        conn.close()


def get_portfolio(db_path: str, agent_id: str, mark_prices=None):
    mark_prices = mark_prices or {}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT agent_id, cash_balance, initial_balance, updated_at
            FROM portfolios
            WHERE agent_id = ?
            """,
            (agent_id,),
        )
        portfolio_row = cursor.fetchone()
        if portfolio_row is None:
            raise ValueError(f"Portfolio not found for agent {agent_id}")

        cursor.execute(
            """
            SELECT asset, quantity, avg_price, updated_at
            FROM positions
            WHERE agent_id = ?
            ORDER BY asset
            """,
            (agent_id,),
        )
        positions_rows = cursor.fetchall()
        positions = []
        position_value = 0.0

        for row in positions_rows:
            market_price = float(mark_prices.get(row["asset"], row["avg_price"]))
            value = float(row["quantity"]) * market_price
            position_value += value
            positions.append(
                {
                    "asset": row["asset"],
                    "quantity": float(row["quantity"]),
                    "avg_price": float(row["avg_price"]),
                    "market_price": market_price,
                    "market_value_eur": round(value, 8),
                    "updated_at": row["updated_at"],
                }
            )

        cash = float(portfolio_row["cash_balance"])
        equity = cash + position_value
        return {
            "agent_id": portfolio_row["agent_id"],
            "cash_balance": round(cash, 8),
            "initial_balance": float(portfolio_row["initial_balance"]),
            "equity": round(equity, 8),
            "positions": positions,
            "updated_at": portfolio_row["updated_at"],
        }
    finally:
        conn.close()


def get_all_portfolios(db_path: str, mark_prices=None):
    mark_prices = mark_prices or {}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT agent_id FROM portfolios ORDER BY agent_id")
        agent_ids = [row["agent_id"] for row in cursor.fetchall()]
    finally:
        conn.close()
    return [get_portfolio(db_path, agent_id, mark_prices=mark_prices) for agent_id in agent_ids]


def record_decision(
    db_path: str,
    agent_id: str,
    asset: str,
    timeframe: str,
    regime: str,
    score: float,
    action: str,
    rationale,
):
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO decisions (
                agent_id, asset, timeframe, regime, score, action, rationale, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent_id,
                asset,
                timeframe,
                regime,
                score,
                action,
                json.dumps(rationale, ensure_ascii=True, sort_keys=True),
                _utc_now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


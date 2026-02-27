from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class PaperOrder:
    agent_id: str
    asset: str
    side: str
    price: float
    notional_eur: float
    reason: str = "strategy_signal"


def execute_paper_order(db_path: str, order: PaperOrder, fee_rate: float = 0.001):
    side = order.side.upper().strip()
    if side not in {"BUY", "SELL"}:
        raise ValueError(f"Unsupported side: {order.side}")
    if order.price <= 0:
        raise ValueError("Order price must be positive.")
    if order.notional_eur <= 0:
        raise ValueError("Order notional must be positive.")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN")

        portfolio = _fetch_portfolio(cursor, order.agent_id)
        if not portfolio:
            raise ValueError(f"Portfolio not found for agent {order.agent_id}")
        cash_balance = float(portfolio["cash_balance"])

        position = _fetch_position(cursor, order.agent_id, order.asset)
        quantity = float(position["quantity"]) if position else 0.0
        avg_price = float(position["avg_price"]) if position else 0.0

        fee = order.notional_eur * fee_rate
        now = _utc_now()

        if side == "BUY":
            total_cost = order.notional_eur + fee
            if cash_balance < total_cost:
                conn.rollback()
                return {
                    "status": "rejected",
                    "reason": "insufficient_cash",
                    "agent_id": order.agent_id,
                    "asset": order.asset,
                    "side": side,
                }

            bought_qty = order.notional_eur / order.price
            new_qty = quantity + bought_qty
            if new_qty <= 0:
                raise ValueError("Calculated quantity is invalid.")
            new_avg_price = (
                ((quantity * avg_price) + (bought_qty * order.price)) / new_qty if quantity else order.price
            )

            _upsert_position(
                cursor,
                agent_id=order.agent_id,
                asset=order.asset,
                quantity=new_qty,
                avg_price=new_avg_price,
                updated_at=now,
            )
            _update_cash(cursor, order.agent_id, cash_balance - total_cost, now)
            traded_qty = bought_qty

        else:
            if quantity <= 0:
                conn.rollback()
                return {
                    "status": "rejected",
                    "reason": "no_position",
                    "agent_id": order.agent_id,
                    "asset": order.asset,
                    "side": side,
                }

            max_notional = quantity * order.price
            sell_notional = min(order.notional_eur, max_notional)
            traded_qty = sell_notional / order.price
            fee = sell_notional * fee_rate
            proceeds = sell_notional - fee
            new_qty = quantity - traded_qty

            if new_qty <= 1e-10:
                _delete_position(cursor, order.agent_id, order.asset)
                new_qty = 0.0
            else:
                _upsert_position(
                    cursor,
                    agent_id=order.agent_id,
                    asset=order.asset,
                    quantity=new_qty,
                    avg_price=avg_price,
                    updated_at=now,
                )
            _update_cash(cursor, order.agent_id, cash_balance + proceeds, now)
            order.notional_eur = sell_notional

        cursor.execute(
            """
            INSERT INTO trades (
                agent_id, asset, side, quantity, price, notional, fee, reason, dry_run, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                order.agent_id,
                order.asset,
                side,
                traded_qty,
                order.price,
                order.notional_eur,
                fee,
                order.reason,
                now,
            ),
        )
        conn.commit()

        return {
            "status": "filled",
            "agent_id": order.agent_id,
            "asset": order.asset,
            "side": side,
            "quantity": round(traded_qty, 10),
            "price": round(order.price, 10),
            "notional_eur": round(order.notional_eur, 8),
            "fee_eur": round(fee, 8),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _fetch_portfolio(cursor, agent_id: str):
    cursor.execute(
        """
        SELECT agent_id, cash_balance
        FROM portfolios
        WHERE agent_id = ?
        """,
        (agent_id,),
    )
    return cursor.fetchone()


def _fetch_position(cursor, agent_id: str, asset: str):
    cursor.execute(
        """
        SELECT quantity, avg_price
        FROM positions
        WHERE agent_id = ? AND asset = ?
        """,
        (agent_id, asset),
    )
    return cursor.fetchone()


def _upsert_position(cursor, agent_id: str, asset: str, quantity: float, avg_price: float, updated_at: str):
    cursor.execute(
        """
        INSERT INTO positions (agent_id, asset, quantity, avg_price, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(agent_id, asset) DO UPDATE SET
            quantity = excluded.quantity,
            avg_price = excluded.avg_price,
            updated_at = excluded.updated_at
        """,
        (agent_id, asset, quantity, avg_price, updated_at),
    )


def _delete_position(cursor, agent_id: str, asset: str):
    cursor.execute(
        """
        DELETE FROM positions
        WHERE agent_id = ? AND asset = ?
        """,
        (agent_id, asset),
    )


def _update_cash(cursor, agent_id: str, new_cash: float, updated_at: str):
    cursor.execute(
        """
        UPDATE portfolios
        SET cash_balance = ?, updated_at = ?
        WHERE agent_id = ?
        """,
        (new_cash, updated_at, agent_id),
    )


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


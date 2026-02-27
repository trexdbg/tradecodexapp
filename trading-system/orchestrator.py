from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from skills.get_market_data import fetch_ohlcv, fetch_top_market_snapshot, timeframe_to_minutes
from skills.get_news import fetch_asset_sentiment
from skills.get_portfolio import get_portfolio, initialize_database, record_decision
from skills.logger import append_event, get_logger
from skills.paper_trade import PaperOrder, execute_paper_order
from skills.scoring import (
    decision_from_score,
    detect_market_regime,
    score_trade_opportunity,
    select_active_strategies,
)

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = ROOT_DIR / "config.json"
DEFAULT_DB_PATH = ROOT_DIR / "database.sqlite"
DEFAULT_LOGS_DIR = ROOT_DIR / "logs"
DEFAULT_DASHBOARD_OUTPUT_PATH = ROOT_DIR.parent / "dashboard" / "data" / "dashboard-data.json"
DEFAULT_EXPORT_SKILL_PATH = ROOT_DIR / "skills" / "export_dashboard.py"
DEFAULT_PUSH_SKILL_PATH = ROOT_DIR / "skills" / "push_github.py"
DEFAULT_REPO_ROOT = ROOT_DIR.parent
ALLOWED_ASSETS = {"BTC", "ETH", "SOL", "BNB", "XRP"}


def main():
    parser = argparse.ArgumentParser(description="Dry-run crypto trading orchestrator")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config.json")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to SQLite database")
    parser.add_argument("--cycles", type=int, default=1, help="Number of cycles to run")
    parser.add_argument(
        "--sleep-seconds",
        type=int,
        default=None,
        help="Sleep between cycles. Defaults to config.execution.cycle_sleep_seconds",
    )
    args = parser.parse_args()

    config_path = _resolve_path(args.config)
    db_path = _resolve_path(args.db)
    config = load_config(config_path)
    validate_config(config)

    logger = get_logger(str(DEFAULT_LOGS_DIR), name="orchestrator")
    initialize_database(
        str(db_path),
        agents=config["agents"],
        starting_capital=float(config["system"]["starting_capital"]),
    )

    sleep_seconds = (
        args.sleep_seconds
        if args.sleep_seconds is not None
        else int(config.get("execution", {}).get("cycle_sleep_seconds", 3))
    )

    logger.info("orchestrator_started | config=%s | db=%s", config_path, db_path)
    for cycle in range(args.cycles):
        summary = run_single_cycle(config=config, db_path=str(db_path), logger=logger)
        logger.info("cycle_complete | cycle=%s | summary=%s", cycle + 1, summary)
        if cycle < args.cycles - 1:
            time.sleep(max(0, sleep_seconds))

    exported_path = _run_dashboard_export(
        db_path=str(db_path),
        output_path=str(DEFAULT_DASHBOARD_OUTPUT_PATH),
        config_path=str(config_path),
        logger=logger,
    )
    append_event(
        str(db_path),
        "dashboard_export",
        {
            "output_path": exported_path,
            "created_at": _utc_now(),
            "cycles": int(args.cycles),
        },
    )
    logger.info("dashboard_export_complete | output=%s", exported_path)
    _maybe_push_github_updates(
        db_path=str(db_path),
        logger=logger,
        exported_path=exported_path,
    )


def run_single_cycle(config, db_path: str, logger):
    assets = config["system"]["supported_assets"]
    lookback = int(config["market_data"].get("lookback_candles", 160))
    min_tf = int(config["system"]["minimum_timeframe_minutes"])
    fee_rate = float(config.get("execution", {}).get("fee_rate", 0.001))
    minimum_order = float(config.get("execution", {}).get("minimum_order_eur", 5.0))
    utc_trade_date = _utc_date()

    sentiment = fetch_asset_sentiment(
        assets,
        config.get("news", {}).get("rss_feeds", []),
        max_items=int(config.get("news", {}).get("max_items", 40)),
    )
    snapshot = fetch_top_market_snapshot(assets)
    mark_prices = {asset: data["last_price"] for asset, data in snapshot.items()}

    summary = {
        "timestamp": _utc_now(),
        "decisions": 0,
        "trades": 0,
        "market_snapshot": snapshot,
    }

    for agent in config["agents"]:
        agent_id = agent["id"]
        timeframe = _shortest_timeframe(agent.get("timeframes", []))
        agent_trades_this_cycle = 0
        agent_prices = {}
        if timeframe_to_minutes(timeframe) < min_tf:
            raise ValueError(
                f"Agent {agent_id} has timeframe {timeframe} below minimum {min_tf} minutes."
            )

        portfolio = get_portfolio(db_path, agent_id, mark_prices=mark_prices)
        logger.info(
            "agent_cycle_start | agent=%s | equity=%.2f | cash=%.2f",
            agent_id,
            portfolio["equity"],
            portfolio["cash_balance"],
        )

        for asset in agent.get("assets", []):
            candles = fetch_ohlcv(
                asset=asset,
                timeframe=timeframe,
                limit=lookback,
                minimum_minutes=min_tf,
            )
            if not candles:
                continue
            latest_price = float(candles[-1]["close"])
            agent_prices[asset] = latest_price

            regime_info = detect_market_regime(candles)
            active_strategies = select_active_strategies(agent, regime_info["regime"])
            score_pack = score_trade_opportunity(
                candles=candles,
                strategies=active_strategies,
                regime_info=regime_info,
                sentiment_score=float(sentiment.get(asset, 0.0)),
            )
            score = float(score_pack["total_score"])
            action = decision_from_score(
                score,
                buy_threshold=float(agent.get("buy_threshold", 0.3)),
                sell_threshold=float(agent.get("sell_threshold", -0.3)),
            )

            rationale = {
                "regime": regime_info,
                "sentiment_score": sentiment.get(asset, 0.0),
                "strategy_scores": score_pack["strategy_scores"],
                "score": score,
            }
            record_decision(
                db_path=db_path,
                agent_id=agent_id,
                asset=asset,
                timeframe=timeframe,
                regime=regime_info["regime"],
                score=score,
                action=action,
                rationale=rationale,
            )
            summary["decisions"] += 1
            logger.info(
                "decision | agent=%s | asset=%s | action=%s | score=%.3f | regime=%s",
                agent_id,
                asset,
                action,
                score,
                regime_info["regime"],
            )

            if action == "HOLD":
                continue

            price = latest_price
            portfolio = get_portfolio(db_path, agent_id, mark_prices={asset: price})
            if action == "BUY":
                notional = _compute_buy_notional(agent, portfolio, conviction=score)
            else:
                current_position = _find_position(portfolio, asset)
                if current_position is None:
                    continue
                notional = _compute_sell_notional(current_position, conviction=score)

            if notional < minimum_order:
                continue

            order = PaperOrder(
                agent_id=agent_id,
                asset=asset,
                side=action,
                price=price,
                notional_eur=notional,
                reason=f"{','.join(active_strategies)}|regime={regime_info['regime']}",
            )
            result = execute_paper_order(db_path=db_path, order=order, fee_rate=fee_rate)
            event_name = "paper_trade" if result["status"] == "filled" else "order_rejected"
            append_event(db_path, event_name, result)
            if result["status"] == "filled":
                summary["trades"] += 1
                agent_trades_this_cycle += 1

            logger.info(
                "order_result | agent=%s | asset=%s | side=%s | status=%s | notional=%.2f",
                agent_id,
                asset,
                action,
                result["status"],
                notional,
            )

        forced_result = _enforce_daily_trade_requirement(
            db_path=db_path,
            agent=agent,
            agent_id=agent_id,
            mark_prices={**mark_prices, **agent_prices},
            minimum_order=minimum_order,
            minimum_timeframe=min_tf,
            fee_rate=fee_rate,
            trade_date=utc_trade_date,
            trades_executed_this_cycle=agent_trades_this_cycle,
            logger=logger,
        )
        if forced_result and forced_result.get("status") == "filled":
            summary["trades"] += 1

    append_event(db_path, "cycle_summary", summary)
    return summary


def load_config(path: Path):
    with path.open("r", encoding="utf-8") as config_file:
        return json.load(config_file)


def validate_config(config):
    system = config.get("system", {})
    if not system.get("dry_run", False):
        raise ValueError("dry_run must be true for this environment.")

    base_currency = str(system.get("base_currency", "EUR")).upper()
    if base_currency != "EUR":
        raise ValueError("base_currency must be EUR.")

    starting_capital = float(system.get("starting_capital", 100.0))
    if abs(starting_capital - 100.0) > 1e-9:
        raise ValueError("starting_capital must be exactly 100 EUR per agent.")

    minimum_timeframe = int(system.get("minimum_timeframe_minutes", 15))
    minimum_order = float(config.get("execution", {}).get("minimum_order_eur", 5.0))
    if minimum_timeframe < 15:
        raise ValueError("minimum_timeframe_minutes must be at least 15.")

    for asset in system.get("supported_assets", []):
        if asset not in ALLOWED_ASSETS:
            raise ValueError(f"Unsupported system asset: {asset}")

    agents = config.get("agents", [])
    if len(agents) < 3:
        raise ValueError("At least 3 agents are required.")
    for agent in agents:
        for asset in agent.get("assets", []):
            if asset not in ALLOWED_ASSETS:
                raise ValueError(f"Agent {agent.get('id')} has unsupported asset {asset}")
        for timeframe in agent.get("timeframes", []):
            if timeframe_to_minutes(timeframe) < minimum_timeframe:
                raise ValueError(
                    f"Agent {agent.get('id')} timeframe {timeframe} below {minimum_timeframe}m."
                )
        if agent.get("force_daily_trade", False):
            daily_asset = str(
                agent.get("daily_trade_asset") or (agent.get("assets", [""])[0] or "")
            ).upper()
            if not daily_asset:
                raise ValueError(
                    f"Agent {agent.get('id')} force_daily_trade requires a daily_trade_asset."
                )
            if daily_asset not in ALLOWED_ASSETS:
                raise ValueError(
                    f"Agent {agent.get('id')} has unsupported daily_trade_asset {daily_asset}"
                )
            configured_assets = {str(asset).upper() for asset in agent.get("assets", [])}
            if daily_asset not in configured_assets:
                raise ValueError(
                    f"Agent {agent.get('id')} daily_trade_asset must be included in assets."
                )

            daily_notional = float(agent.get("daily_trade_notional_eur", minimum_order))
            if daily_notional < minimum_order:
                raise ValueError(
                    f"Agent {agent.get('id')} daily_trade_notional_eur must be >= minimum_order_eur."
                )

            daily_side = str(agent.get("daily_trade_side", "BUY")).upper()
            if daily_side not in {"BUY", "SELL"}:
                raise ValueError(
                    f"Agent {agent.get('id')} daily_trade_side must be BUY or SELL."
                )


def _compute_buy_notional(agent, portfolio, conviction: float):
    equity = float(portfolio["equity"])
    cash = float(portfolio["cash_balance"])
    position_cap = equity * float(agent.get("max_position_pct", 0.2))
    conviction_scale = max(0.25, min(1.0, abs(conviction)))
    target = position_cap * conviction_scale
    cash_buffer = equity * float(agent.get("cash_buffer_pct", 0.1))
    available_cash = max(0.0, cash - cash_buffer)
    return round(max(0.0, min(target, available_cash)), 8)


def _compute_sell_notional(position, conviction: float):
    position_value = float(position["market_value_eur"])
    conviction_scale = max(0.25, min(1.0, abs(conviction)))
    return round(position_value * conviction_scale, 8)


def _enforce_daily_trade_requirement(
    db_path: str,
    agent,
    agent_id: str,
    mark_prices,
    minimum_order: float,
    minimum_timeframe: int,
    fee_rate: float,
    trade_date: str,
    trades_executed_this_cycle: int,
    logger,
):
    if not agent.get("force_daily_trade", False):
        return None

    # Normal strategy trades already satisfy the daily objective.
    if trades_executed_this_cycle > 0:
        return None

    if _agent_has_trade_on_date(db_path, agent_id, trade_date):
        return None

    daily_asset = str(
        agent.get("daily_trade_asset") or (agent.get("assets", [None])[0] or "")
    ).upper()
    if not daily_asset:
        logger.warning(
            "daily_trade_enforcement_skipped | agent=%s | reason=missing_daily_trade_asset",
            agent_id,
        )
        append_event(
            db_path,
            "daily_trade_enforcement_skipped",
            {
                "agent_id": agent_id,
                "reason": "missing_daily_trade_asset",
                "trade_date": trade_date,
                "created_at": _utc_now(),
            },
        )
        return None

    portfolio = get_portfolio(db_path, agent_id, mark_prices=mark_prices)
    requested_side = str(agent.get("daily_trade_side", "BUY")).upper()
    side = requested_side if requested_side in {"BUY", "SELL"} else "BUY"
    target_notional = max(minimum_order, float(agent.get("daily_trade_notional_eur", minimum_order)))
    price = float(mark_prices.get(daily_asset, 0.0))

    if price <= 0.0:
        candles = fetch_ohlcv(
            asset=daily_asset,
            timeframe=_shortest_timeframe(agent.get("timeframes", [])),
            limit=2,
            minimum_minutes=minimum_timeframe,
        )
        if not candles:
            logger.warning(
                "daily_trade_enforcement_skipped | agent=%s | asset=%s | reason=no_price_data",
                agent_id,
                daily_asset,
            )
            append_event(
                db_path,
                "daily_trade_enforcement_skipped",
                {
                    "agent_id": agent_id,
                    "asset": daily_asset,
                    "reason": "no_price_data",
                    "trade_date": trade_date,
                    "created_at": _utc_now(),
                },
            )
            return None
        price = float(candles[-1]["close"])

    max_affordable_buy = float(portfolio["cash_balance"]) / (1.0 + fee_rate)
    if side == "BUY":
        notional = min(target_notional, max_affordable_buy)
        if notional < minimum_order:
            sell_position = _select_sell_position(portfolio, preferred_asset=daily_asset)
            if sell_position is None:
                logger.warning(
                    "daily_trade_enforcement_failed | agent=%s | reason=insufficient_cash_and_no_position",
                    agent_id,
                )
                append_event(
                    db_path,
                    "daily_trade_enforcement_failed",
                    {
                        "agent_id": agent_id,
                        "reason": "insufficient_cash_and_no_position",
                        "trade_date": trade_date,
                        "created_at": _utc_now(),
                    },
                )
                return None
            side = "SELL"
            daily_asset = str(sell_position["asset"]).upper()
            price = _position_price(sell_position, mark_prices)
            notional = min(target_notional, float(sell_position["market_value_eur"]))
    else:
        sell_position = _select_sell_position(portfolio, preferred_asset=daily_asset)
        if sell_position is None or float(sell_position["market_value_eur"]) < minimum_order:
            if max_affordable_buy < minimum_order:
                logger.warning(
                    "daily_trade_enforcement_failed | agent=%s | reason=no_sell_position_and_not_enough_cash",
                    agent_id,
                )
                append_event(
                    db_path,
                    "daily_trade_enforcement_failed",
                    {
                        "agent_id": agent_id,
                        "reason": "no_sell_position_and_not_enough_cash",
                        "trade_date": trade_date,
                        "created_at": _utc_now(),
                    },
                )
                return None
            side = "BUY"
            notional = min(target_notional, max_affordable_buy)
        else:
            daily_asset = str(sell_position["asset"]).upper()
            price = _position_price(sell_position, mark_prices)
            notional = min(target_notional, float(sell_position["market_value_eur"]))

    if notional < minimum_order:
        logger.warning(
            "daily_trade_enforcement_failed | agent=%s | reason=notional_below_minimum | notional=%.4f",
            agent_id,
            notional,
        )
        append_event(
            db_path,
            "daily_trade_enforcement_failed",
            {
                "agent_id": agent_id,
                "reason": "notional_below_minimum",
                "notional_eur": round(notional, 8),
                "trade_date": trade_date,
                "created_at": _utc_now(),
            },
        )
        return None

    order = PaperOrder(
        agent_id=agent_id,
        asset=daily_asset,
        side=side,
        price=price,
        notional_eur=round(notional, 8),
        reason=f"mandatory_daily_trade|date={trade_date}",
    )
    result = execute_paper_order(db_path=db_path, order=order, fee_rate=fee_rate)
    event_name = "paper_trade" if result["status"] == "filled" else "order_rejected"
    append_event(db_path, event_name, result)
    append_event(
        db_path,
        "daily_trade_enforced",
        {
            "agent_id": agent_id,
            "trade_date": trade_date,
            "requested_side": requested_side,
            "result": result,
            "created_at": _utc_now(),
        },
    )
    logger.info(
        "daily_trade_enforced | agent=%s | asset=%s | side=%s | status=%s | notional=%.2f",
        agent_id,
        daily_asset,
        side,
        result.get("status"),
        notional,
    )
    return result


def _select_sell_position(portfolio, preferred_asset: str):
    positions = portfolio.get("positions", [])
    preferred = next((item for item in positions if item["asset"] == preferred_asset), None)
    if preferred:
        return preferred
    if not positions:
        return None
    return max(positions, key=lambda item: float(item["market_value_eur"]))


def _position_price(position, mark_prices):
    asset = position["asset"]
    market_price = float(mark_prices.get(asset, 0.0))
    if market_price > 0.0:
        return market_price

    position_price = float(position.get("market_price", 0.0))
    if position_price > 0.0:
        return position_price

    return float(position.get("avg_price", 0.0))


def _find_position(portfolio, asset: str):
    for position in portfolio.get("positions", []):
        if position["asset"] == asset:
            return position
    return None


def _shortest_timeframe(timeframes):
    if not timeframes:
        return "15m"
    return sorted(timeframes, key=timeframe_to_minutes)[0]


def _resolve_path(path_str: str) -> Path:
    path = Path(path_str)
    if path.is_absolute():
        return path
    return (ROOT_DIR / path).resolve()


def _run_dashboard_export(db_path: str, output_path: str, config_path: str, logger):
    command = [
        sys.executable,
        str(DEFAULT_EXPORT_SKILL_PATH),
        "--db",
        db_path,
        "--config",
        config_path,
        "--out",
        output_path,
    ]
    completed = subprocess.run(
        command,
        cwd=str(DEFAULT_REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Dashboard export failed: {(completed.stderr or completed.stdout).strip()}"
        )
    stdout = completed.stdout.strip()
    if stdout:
        logger.info("dashboard_export_stdout | %s", stdout)
    return output_path


def _maybe_push_github_updates(db_path: str, logger, exported_path: str):
    if not _is_git_push_configured(DEFAULT_REPO_ROOT):
        append_event(
            db_path,
            "push_github_skipped",
            {
                "reason": "git_credentials_not_configured",
                "created_at": _utc_now(),
            },
        )
        logger.info("push_github_skipped | reason=git_credentials_not_configured")
        return

    relative_db = str(DEFAULT_DB_PATH.relative_to(DEFAULT_REPO_ROOT))
    relative_export = str(Path(exported_path).resolve().relative_to(DEFAULT_REPO_ROOT))
    relative_log = str((DEFAULT_LOGS_DIR / "orchestrator.log").relative_to(DEFAULT_REPO_ROOT))
    command = [
        sys.executable,
        str(DEFAULT_PUSH_SKILL_PATH),
        "--message",
        "chore: update trading snapshot",
        "--paths",
        relative_db,
        relative_export,
        relative_log,
    ]
    completed = subprocess.run(
        command,
        cwd=str(DEFAULT_REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    output = (completed.stdout or completed.stderr).strip()
    if completed.returncode == 0:
        append_event(
            db_path,
            "push_github",
            {
                "status": "ok",
                "output": output,
                "created_at": _utc_now(),
            },
        )
        logger.info("push_github_complete | output=%s", output or "<empty>")
        return

    append_event(
        db_path,
        "push_github_error",
        {
            "status": "failed",
            "output": output,
            "created_at": _utc_now(),
        },
    )
    logger.warning("push_github_failed | output=%s", output or "<empty>")


def _is_git_push_configured(repo_root: Path):
    checks = [
        ["git", "rev-parse", "--is-inside-work-tree"],
        ["git", "remote", "get-url", "origin"],
        ["git", "config", "--get", "user.name"],
        ["git", "config", "--get", "user.email"],
    ]
    for command in checks:
        result = subprocess.run(
            command,
            cwd=str(repo_root),
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return False

    branch_probe = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
    )
    branch = branch_probe.stdout.strip()
    if branch_probe.returncode != 0 or not branch or branch == "HEAD":
        return False
    return True


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _utc_date():
    return datetime.now(timezone.utc).date().isoformat()


def _agent_has_trade_on_date(db_path: str, agent_id: str, trade_date: str):
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT 1
            FROM trades
            WHERE agent_id = ? AND substr(created_at, 1, 10) = ?
            LIMIT 1
            """,
            (agent_id, trade_date),
        )
        return cursor.fetchone() is not None
    finally:
        conn.close()


if __name__ == "__main__":
    main()

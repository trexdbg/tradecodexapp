# Trading System Skills

This environment exposes backend "skills" used by the trading orchestrator.

## Skill Inventory

- `skills/get_market_data.py`
  - Pulls OHLCV candles and 24h snapshots for `BTC`, `ETH`, `SOL`, `BNB`, `XRP`.
  - Enforces a minimum timeframe of 15 minutes.
  - Falls back to synthetic market data if the remote provider is unavailable.

- `skills/get_news.py`
  - Reads crypto RSS feeds.
  - Computes lightweight sentiment per asset from title and description keywords.

- `skills/scoring.py`
  - Detects market regime (`trending` or `ranging`) from recent candles.
  - Scores strategy signals: `mean_reversion`, `trend_follow`, `breakout_confirmation`, `sentiment_filter`.
  - Converts score to action (`BUY`, `SELL`, `HOLD`).

- `skills/get_portfolio.py`
  - Creates and manages SQLite schema for agents, portfolios, positions, trades, and decisions.
  - Returns per-agent and global portfolio snapshots.

- `skills/paper_trade.py`
  - Executes dry-run orders against the SQLite portfolio.
  - Applies fees and updates cash, positions, and trade logs atomically.

- `skills/live_trade.py`
  - Live trading stub intentionally disabled while system is in dry-run mode.

- `skills/logger.py`
  - Configures structured file logging in `logs/orchestrator.log`.
  - Writes JSON events to SQLite `events` table.

- `skills/export_dashboard.py`
  - Exports SQLite trading state to a static JSON snapshot for frontend dashboards.
  - Produces aggregated KPIs, per-agent performance, recent decisions/trades/events, and score series.
  - Can be executed directly as a CLI export command.

- `skills/push_github.py`
  - Stages local changes, creates a commit, and pushes to a remote branch.
  - Supports `--paths` for targeted staging and `--dry-run` for safe preview.

## Runtime Contract

- Base currency: `EUR`
- Initial capital per agent: `100.0 EUR`
- Minimum timeframe: `15m`
- Trading mode: dry-run only

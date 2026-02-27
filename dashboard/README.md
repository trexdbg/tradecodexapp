# Dashboard Frontend

This folder contains the static dashboard frontend for GitHub Pages.

## Data source

The dashboard reads `./data/dashboard-data.json`.

Generate it from the SQLite database with:

```bash
python trading-system/skills/export_dashboard.py
```

Optional flags:

```bash
python trading-system/skills/export_dashboard.py --db trading-system/database.sqlite --out dashboard/data/dashboard-data.json --decisions-limit 500 --trades-limit 300
```

## Publish on GitHub Pages

1. In repository settings, enable GitHub Pages from branch root and folder `/dashboard`.
2. Commit and push `dashboard/` including `dashboard/data/dashboard-data.json`.
3. Re-run the export command whenever new orchestrator data is available.

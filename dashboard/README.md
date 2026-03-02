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

1. Keep `.github/workflows/deploy-pages-dashboard.yml` in the repository.
2. In repository settings, open `Pages` and set:
   - Source: `GitHub Actions`
3. Commit and push `dashboard/` including `dashboard/data/dashboard-data.json`.
4. Open the dashboard URL:
   - `https://<github-user>.github.io/<repo>/`
5. Re-run the export command whenever new orchestrator data is available.

Notes:
- GitHub Pages serves static files behind CDN cache (`max-age=600`).
- The workflow publishes `dashboard/` as the Pages site root.
- `app.js` already adds a cache-busting query string when loading JSON data.
- If the repository previously used `Deploy from a branch`, switch to `GitHub Actions` to avoid mixed deployment behavior.

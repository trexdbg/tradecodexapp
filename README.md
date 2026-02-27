# cryptoMaster

Application de simulation de trading crypto avec:
- un backend Python multi-agents (`trading-system/`)
- un dashboard statique HTML/CSS/JS (`dashboard/`)

Le systeme fonctionne en **dry-run uniquement** (pas de trading live).

## Apercu

- 3 agents de trading avec profils de risque differents.
- Actifs supportes: `BTC`, `ETH`, `SOL`, `BNB`, `XRP`.
- Decisions et trades stockes en SQLite (`trading-system/database.sqlite`).
- Export des donnees vers `dashboard/data/dashboard-data.json`.
- Dashboard consultable localement ou via GitHub Pages.

## Structure du projet

```text
cryptoMaster/
|- trading-system/
|  |- orchestrator.py
|  |- config.json
|  |- skills/
|  `- database.sqlite
|- dashboard/
|  |- index.html
|  |- app.js
|  |- styles.css
|  `- data/
`- README.md
```

## Prerequis

- Python 3.10+ (aucune dependance tierce obligatoire)
- Un navigateur web moderne

## Demarrage rapide

1. Lancer 1 cycle de simulation:

```bash
python trading-system/orchestrator.py --cycles 1
```

2. Exporter les donnees pour le dashboard:

```bash
python trading-system/skills/export_dashboard.py
```

3. Servir le projet en local (recommande, car `fetch` JSON peut etre bloque en `file://`):

```bash
python -m http.server 8000
```

4. Ouvrir:

- `http://localhost:8000/dashboard/`

## Commandes utiles

Lancer plusieurs cycles:

```bash
python trading-system/orchestrator.py --cycles 20 --sleep-seconds 3
```

Utiliser un autre fichier de config ou DB:

```bash
python trading-system/orchestrator.py --config trading-system/config.json --db trading-system/database.sqlite
```

Exporter vers un autre dossier (ex: `docs/`):

```bash
python trading-system/skills/export_dashboard.py --out docs/data/dashboard-data.json
```

Limiter le volume exporte:

```bash
python trading-system/skills/export_dashboard.py --decisions-limit 500 --trades-limit 300 --events-limit 150
```

Commit + push sur GitHub (avec message):

```bash
python trading-system/skills/push_github.py --message "chore: update dashboard data"
```

## Configuration

Le fichier `trading-system/config.json` controle:
- les regles systeme (`dry_run`, capital initial, timeframe minimum)
- les agents (assets, strategies, seuils buy/sell)
- les parametres execution (frais, minimum ordre, pause entre cycles)
- les flux RSS pour le sentiment news

## Pipeline de donnees

1. `orchestrator.py` recupere marche + news.
2. Les strategies scorent les opportunites (`BUY`/`SELL`/`HOLD`).
3. `paper_trade.py` simule les ordres en base SQLite.
4. `skills/export_dashboard.py` genere un JSON statique.
5. `dashboard/app.js` lit ce JSON et rend les KPIs, tables et graphes.

# cryptoMaster

Application de simulation de trading crypto avec:
- un backend Python multi-agents (`trading-system/`)
- un dashboard statique HTML/CSS/JS (`dashboard/`)

Le systeme fonctionne en **dry-run uniquement** (pas de trading live).

## Apercu

- Plusieurs agents de trading avec profils de risque differents.
- Support des positions long et short en dry-run (agents avec `allow_short: true`).
- Actifs supportes: `BTC`, `ETH`, `SOL`, `BNB`, `XRP`.
- Decisions et trades stockes en SQLite (`trading-system/database.sqlite`).
- Export des donnees vers `dashboard/data/dashboard-data.json`.
- Dashboard consultable localement ou via GitHub Pages (publie a la racine du site).
- Garde-fous de rentabilite: cooldown par actif, prises de profit/pertes automatiques, limite de concentration.
- Garde-fous de qualite des donnees: priorite aux sources live, blocage des ordres quand seules des donnees synthetiques sont disponibles.

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

Creer un agent (dry-run):

```bash
python trading-system/skills/create_agent.py --id agent_06_swing --name "Swing Pulse" --risk-profile balanced --assets BTC,ETH --timeframes 15m,1h --dry-run
```

Creer un agent short-capable Hyperliquid:

```bash
python trading-system/skills/create_agent.py --id agent_09_codex_hyperliquid_ls --name "Codex Hyperliquid LS Core" --risk-profile balanced --assets BTC,ETH,SOL --timeframes 15m,1h --allow-short --exchange hyperliquid
```

Lancer un backtest walk-forward (train/test + benchmark buy&hold):

```bash
python trading-system/skills/backtest_walk_forward.py --out trading-system/data/backtest-walkforward.json
```

Run rapide sur un agent:

```bash
python trading-system/skills/backtest_walk_forward.py --agents agent_07_risky_scalper --lookback-candles 260 --warmup-candles 40 --train-candles 80 --test-candles 40 --step-candles 40 --out trading-system/data/backtest-riskiest-smoke.json
```

## Configuration

Le fichier `trading-system/config.json` controle:
- les regles systeme (`dry_run`, capital initial, timeframe minimum)
- un mode realiste (`system.realistic_mode: true`) qui bloque les trades forces (`force_daily_trade`)
- les agents (assets, strategies, seuils buy/sell)
- les parametres execution (frais, slippage en bps, minimum ordre, pause entre cycles, rotation quotidienne des top paires volume a minuit)
- les flux RSS pour le sentiment news
- les presets de strategie via `risk_profile` (utile pour creer rapidement de nouveaux agents)

Un agent peut maintenant etre defini en mode minimal:
- `id`, `name`, `risk_profile`, `assets`, `timeframes`
- puis overrides optionnels selon besoin (strategies custom, seuils, garde-fous, daily trade)
- options de direction: `allow_short` et `exchange` (ex: `hyperliquid`)

Template de depart: `trading-system/agent-template.json`.

## Pipeline de donnees

1. `orchestrator.py` recupere marche + news.
2. Les strategies scorent les opportunites (`BUY`/`SELL`/`HOLD`).
3. `paper_trade.py` simule les ordres en base SQLite.
4. `skills/export_dashboard.py` genere un JSON statique.
5. `dashboard/app.js` lit ce JSON et rend les KPIs, tables et graphes.

## Deploiement GitHub Pages

- Le workflow `.github/workflows/deploy-pages-dashboard.yml` publie le contenu de `dashboard/` comme racine du site Pages.
- Dans `Settings > Pages`, choisir `Source: GitHub Actions`.
- URL finale: `https://<github-user>.github.io/<repo>/`.

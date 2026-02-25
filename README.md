# Thrive Analytics

Analytics dashboard and reporting suite for Thrive Cannabis Nevada — processing Flowhub POS data across 7 dispensary locations in Las Vegas, Henderson, Reno, and Jackpot.

**Live dashboard:** [thrive-analytics.vercel.app](https://thrive-analytics.vercel.app)

## Architecture

- **Modular Python app** in `app/` — data loading, analytics, report generation, API, and Excel output
- **JSON-first**: every report has a `generate_json()` function; Excel output renders from JSON
- **Static site export**: `python3 -m app.cli export` pre-computes all JSON files and generates a self-contained dashboard in `public/`
- **Deployed on Vercel** as a static site with pre-built JSON data files

## Dashboard Pages

| Page | Description |
|------|-------------|
| **Executive Summary** | Revenue, margin, transactions, units — KPI cards + trend chart + top categories/stores |
| **Month over Month** | Side-by-side monthly comparison with YoY context |
| **Store Performance** | Per-store KPIs, revenue/margin charts, performance table |
| **Brand Reports** | Per-brand dispensary and brand-facing reports with deals, products, store breakdown |
| **Master Reports** | Margin, Deals, Budtender, Customer, and Rewards analysis |

## Reports

### Brand Reports (per brand)
- **Dispensary Report** (12 sections): Exec Summary, Trend, Product Type, Share of Category, Discount Depth, Deal Performance, Top Products, Products by Store, By Store, Velocity, Comparison Period, Recommendations
- **Brand Facing** (9 sections): Exec Summary, Distribution Scorecard, Share of Category, Velocity Benchmarking, Store Gap Analysis, Product Mix, Pricing Consistency, Promotional Effectiveness, Growth Opportunities

### Master Suite (5 reports)
- **Margin Report** — Full price vs discounted sales, margin analysis by store/brand/category
- **Deal Performance** — Deal classification, top deals, effectiveness by type
- **Budtender Performance** — Sales scoring (0-100), cart value, discount discipline, per-store ranking
- **Customer Insights** — Segments, loyalty, top customers by store
- **Rewards & Markout** — Program costs, employee usage, product breakdown

## Data Pipeline

1. **Input**: Flowhub margin report CSVs dropped into `inbox/` (organized by year subdirectories)
2. **Loading**: Multi-file discovery, column normalization, category cleanup, deduplication
3. **Cost correction**: In-house brand costs are corrected where Flowhub data is unreliable (see below)
4. **Classification**: Transactions tagged as REGULAR/REWARD/MARKOUT/TESTER/COMP; deals classified by type
5. **Output**: JSON files for dashboard, Excel workbooks for download

## In-House Brand Cost Corrections

Flowhub cost data is unreliable for in-house brands. Corrections are applied unconditionally for 2024, 2025, and 2026:

| Brand | Default (per unit) | Pre-Roll (per unit) |
|-------|-------------------|-------------------|
| HAUS | $6.62 | $4.00 |
| HUSTLE & GROW | $6.62 | $4.00 |
| PISTOLA | $8.63 | $4.00 |
| GREEN & GOLD | $8.63 | $4.00 |

| Brand | Cart (per unit) | Disposable (per unit) |
|-------|----------------|----------------------|
| FADE | $10.61 | $12.44 |
| RETREAT | $10.61 | $12.44 |

## Quick Start

### Prerequisites
- Python 3.10+
- Dependencies: `pip install -r requirements.txt`

### Run the Dashboard Locally
```bash
# Generate static site
python3 -m app.cli export --output ./public

# Serve locally
python3 -m http.server 8080 -d public
```

### Generate Excel Reports
```bash
# Brand report
python3 -m app.cli brand "WYLD"

# Master suite
python3 -m app.cli master
```

### Run the API Server
```bash
python3 -m app.cli serve
```

### Deploy to Vercel
```bash
python3 -m app.cli export --output ./public
git add public vercel.json && git push
```

## Project Structure
```
Thrive Analytics/
├── app/
│   ├── config.py          # Paths, column map, cost corrections, constants
│   ├── cli.py             # CLI: brand, master, serve, export commands
│   ├── main.py            # FastAPI app factory
│   ├── data/
│   │   ├── loader.py      # CSV discovery, loading, dedup, cost correction
│   │   ├── store.py       # DataStore — in-memory query engine
│   │   ├── schemas.py     # PeriodFilter, PeriodType, enums
│   │   └── normalize.py   # Column/category normalization
│   ├── analytics/         # Aggregation and metric computation
│   ├── reports/           # JSON report generators (brand, master)
│   ├── excel/             # Excel workbook output
│   ├── api/               # FastAPI route handlers
│   └── static/            # HTML template for static export
├── public/                # Generated static site (deployed to Vercel)
│   ├── index.html
│   └── data/              # Pre-computed JSON files (~1,670 files)
├── inbox/                 # Raw Flowhub CSV input files
├── reports/               # Generated Excel reports
├── vercel.json            # Vercel deployment config
└── requirements.txt
```

## Data Scale
- ~4.9M unique transaction rows across 26 CSV files
- 7 stores, 312 brands, 25 months (Jan 2024 – Jan 2026)
- Static export: ~1,670 JSON files, ~41 MB

---
*Thrive Cannabis Nevada — Las Vegas, Henderson, Reno, Jackpot*

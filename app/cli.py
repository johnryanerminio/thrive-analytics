#!/usr/bin/env python3
"""
Thrive Analytics CLI — Unified entry point for brand reports, master suite, and API server.

USAGE:
  python -m app.cli brand "STIIIZY"                        # Single brand report
  python -m app.cli brand "STIIIZY" "WYLD" "FADE"          # Multiple brands
  python -m app.cli brand --top 10                          # Top 10 by revenue
  python -m app.cli brand --list                            # List available brands
  python -m app.cli brand --facing "STIIIZY"                # Brand-facing report

  python -m app.cli master                                  # Generate all 5 master reports
  python -m app.cli master --period month --year 2025 --month 12

  python -m app.cli serve                                   # Start API server
  python -m app.cli serve --port 8000

  python -m app.cli export                                  # Export static site to public/
  python -m app.cli export --output ./dist                  # Custom output directory
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import BASE_FOLDER, BRAND_REPORTS_FOLDER, REPORTS_FOLDER
from app.data.store import DataStore
from app.data.schemas import PeriodFilter, PeriodType


def _build_period(args) -> PeriodFilter | None:
    """Build a PeriodFilter from CLI args."""
    pt = getattr(args, "period", None)
    if pt is None:
        return None
    return PeriodFilter(
        period_type=PeriodType(pt),
        year=getattr(args, "year", None),
        month=getattr(args, "month", None),
        quarter=getattr(args, "quarter", None),
    )


def cmd_brand(args):
    """Generate brand reports."""
    print("\n" + "=" * 70)
    print("  THRIVE ANALYTICS — BRAND REPORT GENERATOR")
    print("=" * 70)

    store = DataStore().load()
    period = _build_period(args)
    date_range = store.date_range(period)
    brands = store.brands()

    if args.list:
        regular = store.get_regular(period)
        brand_rev = regular.groupby("brand_clean", observed=True)["actual_revenue"].sum().sort_values(ascending=False)
        print(f"\nBRANDS ({len(brand_rev)}):\n")
        for i, (b, rev) in enumerate(brand_rev.items(), 1):
            print(f"{i:<4}{b[:40]:<42}${rev:>12,.2f}")
            if i >= 50:
                break
        return

    # Determine which brands to process
    brands_to_process = []
    if args.top:
        brands_to_process = brands[:args.top]
    elif args.facing:
        brands_to_process = args.facing
    elif args.brands:
        for req in args.brands:
            match = next((b for b in brands if b.upper() == req.upper()), None)
            if match:
                brands_to_process.append(match)
            else:
                print(f"  Brand not found: '{req}'")
    else:
        print("  Specify brand name(s), --top N, --list, or --facing <brand>")
        return

    BRAND_REPORTS_FOLDER.mkdir(parents=True, exist_ok=True)

    if args.facing:
        # Brand-facing reports
        from app.reports.brand_facing import generate_json, generate_excel
        print(f"\nGenerating {len(brands_to_process)} brand-facing report(s)...\n")
        for brand_name in brands_to_process:
            match = next((b for b in brands if b.upper() == brand_name.upper()), None)
            if not match:
                print(f"  Brand not found: '{brand_name}'")
                continue
            safe = match.replace("/", "-").replace("\\", "-")[:40]
            out = BRAND_REPORTS_FOLDER / f"Brand_Facing_{safe}.xlsx"
            generate_excel(store, match, out, period)
            data = generate_json(store, match, period)
            s = data["summary"]
            print(f"   {match}")
            print(f"      ${s['total_revenue']:,.0f}  |  Coverage: {s['store_coverage']}  |  Velocity: #{s['velocity_rank']}")
    else:
        # Dispensary-side brand reports
        from app.reports.brand_dispensary import generate_json, generate_excel
        comparison = period.previous() if period else None
        print(f"\nGenerating {len(brands_to_process)} brand report(s)...\n")
        for brand_name in brands_to_process:
            match = next((b for b in brands if b.upper() == brand_name.upper()), None)
            if not match:
                print(f"  Brand not found: '{brand_name}'")
                continue
            brand_df = store.get_brand(match, period)
            if len(brand_df) < 5:
                continue
            safe = match.replace("/", "-").replace("\\", "-")[:40]
            out = BRAND_REPORTS_FOLDER / f"Brand_Report_{safe}.xlsx"
            generate_excel(store, match, out, period, comparison)
            data = generate_json(store, match, period, comparison)
            s = data["summary"]
            icon = "+" if s["margin_vs_category"] >= 0 else "-"
            rank_str = f"#{s['category_rank']}/{s['category_total']}" if s["category_rank"] > 0 else ""
            print(f"   [{icon}] {match}")
            print(f"      ${s['total_revenue']:,.0f}  |  {s['overall_margin']:.1f}%  |  {s['primary_category']} {rank_str}")

    print(f"\nReports saved to: {BRAND_REPORTS_FOLDER}\n")


def cmd_master(args):
    """Generate all 5 master suite reports."""
    print("\n" + "=" * 70)
    print("  THRIVE ANALYTICS — MASTER SUITE")
    print("=" * 70)
    print(f"  Started: {datetime.now():%Y-%m-%d %H:%M:%S}")

    store = DataStore().load()
    period = _build_period(args)
    date_range = store.date_range(period)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_folder = REPORTS_FOLDER / timestamp
    output_folder.mkdir(parents=True, exist_ok=True)

    print(f"\n  Period: {date_range}")
    print(f"  Generating reports...\n")

    from app.reports.margin_report import generate_excel as margin_excel
    margin_excel(store, output_folder / "Margin_Report.xlsx", period)
    print("   Margin_Report.xlsx")

    from app.reports.deal_report import generate_excel as deal_excel
    deal_excel(store, output_folder / "Deal_Performance_Report.xlsx", period)
    print("   Deal_Performance_Report.xlsx")

    from app.reports.budtender_report import generate_excel as bt_excel
    try:
        bt_excel(store, output_folder / "Budtender_Performance_Report.xlsx", period)
        print("   Budtender_Performance_Report.xlsx")
    except ValueError:
        print("   (Skipped Budtender report — no BT data)")

    from app.reports.customer_report import generate_excel as cust_excel
    cust_excel(store, output_folder / "Customer_Insights_Report.xlsx", period)
    print("   Customer_Insights_Report.xlsx")

    from app.reports.rewards_report import generate_excel as rew_excel
    rew_excel(store, output_folder / "Rewards_Markout_Report.xlsx", period)
    print("   Rewards_Markout_Report.xlsx")

    print(f"\n  Reports saved to: {output_folder}")
    print("=" * 70 + "\n")


def _brand_slug(name: str) -> str:
    """Convert brand name to a filesystem-safe slug."""
    s = name.lower().strip()
    s = unicodedata.normalize("NFKD", s)
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return s or "unknown"


def _write_json(path: Path, data):
    """Write sanitised JSON to path, creating parent dirs."""
    from app.analytics.common import sanitize_for_json
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = sanitize_for_json(data)
    with open(path, "w") as f:
        json.dump(clean, f, separators=(",", ":"), default=str)


def _period_key(pf: PeriodFilter | None) -> str:
    if pf is None:
        return "all"
    return f"{pf.year}-{pf.month:02d}"


def _checked_replace(html: str, old: str, new: str, label: str) -> str:
    if old not in html:
        print(f"  WARNING: Could not patch '{label}' — pattern not found")
        return html
    return html.replace(old, new, 1)


def _generate_static_index(out: Path):
    """Read app/static/index.html and patch it for static-file mode."""
    src = Path(__file__).parent / "static" / "index.html"
    html = src.read_text()

    # --- 1. Replace api() method with static file resolver ---
    old_api = """    async api(path, params = {}) {
      const url = new URL(path, location.origin);
      for (const [k, v] of Object.entries(params)) {
        if (v !== null && v !== undefined && v !== '') url.searchParams.set(k, v);
      }
      const r = await fetch(url);
      if (!r.ok) throw new Error(await r.text().catch(() => r.statusText));
      return r.json();
    },"""

    new_api = """    async api(path, params = {}) {
      const url = this._resolvePath(path, params);
      const r = await fetch(url);
      if (!r.ok) {
        if (path.includes('/brands/') && (path.endsWith('/report') || path.endsWith('/facing'))) {
          const brand = decodeURIComponent(path.split('/')[3]);
          const slug = this._brandSlugs[brand] || brand.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
          const suffix = path.endsWith('/report') ? 'report' : 'facing';
          const fallback = '/data/brands/' + slug + '/' + suffix + '.json';
          if (fallback !== url) {
            const r2 = await fetch(fallback);
            if (r2.ok) return r2.json();
          }
        }
        throw new Error('Data not available for this selection');
      }
      return r.json();
    },

    _resolvePath(path, params) {
      const pk = (params.period_type === 'month' && params.year && params.month)
        ? params.year + '-' + String(params.month).padStart(2, '0')
        : 'all';
      if (path === '/api/health') return '/data/health.json';
      if (path === '/api/brands') return '/data/brands.json';
      if (path === '/api/stores') return '/data/stores.json';
      if (path === '/api/periods') return '/data/periods.json';
      if (path === '/api/executive-summary') return '/data/exec/' + pk + '.json';
      if (path === '/api/month-over-month') return '/data/mom/' + pk + '.json';
      if (path === '/api/store-performance') return '/data/stores-perf/' + pk + '.json';
      if (path === '/api/year-end-summary') return '/data/yearend/' + (params.year || '2025') + '.json';
      if (path.includes('/brands/') && path.endsWith('/report')) {
        const brand = decodeURIComponent(path.split('/')[3]);
        const slug = this._brandSlugs[brand] || brand.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
        if (pk !== 'all') { const yr = pk.split('-')[0]; return '/data/brands/' + slug + '/report-' + yr + '.json'; }
        return '/data/brands/' + slug + '/report.json';
      }
      if (path.includes('/brands/') && path.endsWith('/facing')) {
        const brand = decodeURIComponent(path.split('/')[3]);
        const slug = this._brandSlugs[brand] || brand.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
        if (pk !== 'all') { const yr = pk.split('-')[0]; return '/data/brands/' + slug + '/facing-' + yr + '.json'; }
        return '/data/brands/' + slug + '/facing.json';
      }
      if (path.startsWith('/api/master/')) {
        const tab = path.split('/')[3];
        if (params.store && this._storeSlugs[params.store]) return '/data/master/' + tab + '/' + this._storeSlugs[params.store] + '.json';
        return '/data/master/' + tab + '.json';
      }
      if (path === '/api/upload/files') return '/data/health.json';
      return path;
    },"""

    html = _checked_replace(html, old_api, new_api, "api() method")

    # --- 2. Add _brandSlugs to state ---
    html = _checked_replace(html,
        "_charts: {},",
        "_charts: {},\n    _brandSlugs: {},\n    _storeSlugs: {},\n    masterStore: '',\n    _initialized: false,",
        "_brandSlugs state")

    # --- 3. Populate _brandSlugs in init ---
    html = _checked_replace(html,
        "this.brands = b.brands || b || [];",
        "this.brands = b.brands || b || [];\n      this._brandSlugs = b.brand_slugs || {};\n      this._storeSlugs = s.store_slugs || {};",
        "_brandSlugs init")

    # --- 4. Remove store filter from periodParams ---
    html = _checked_replace(html,
        "if (this.selectedStore) p.store = this.selectedStore;",
        "// store filter disabled in static mode",
        "selectedStore in periodParams")

    # --- 5. Remove Data Manager from loadCurrentView ---
    html = _checked_replace(html,
        "else if (this.view === 'datamanager') this.loadDMFiles();",
        "",
        "datamanager in loadCurrentView")

    # --- 6. Remove Data Manager nav item ---
    dm_nav_pattern = re.compile(
        r'\s*<!-- Data Manager -->\s*<div class="nav-item".*?</div>\s*</nav>',
        re.DOTALL,
    )
    html = dm_nav_pattern.sub("\n    </nav>", html, count=1)

    # --- 7. Remove the Data Manager section ---
    dm_section_pattern = re.compile(
        r'<!-- =+ -->\s*<!-- DATA MANAGER PAGE.*?</section>',
        re.DOTALL,
    )
    html = dm_section_pattern.sub("", html, count=1)

    # --- 8. Remove datamanager from pageTitle ---
    html = html.replace(", datamanager:'Data Manager'", "")
    html = html.replace(",datamanager:'Data Manager'", "")

    # --- 9. Hide the store filter dropdowns (desktop + mobile) ---
    # Desktop: add hidden class
    html = _checked_replace(html,
        'class="hidden md:block px-3 py-2 text-sm border border-muted rounded-lg bg-[#161922]',
        'class="hidden px-3 py-2 text-sm border border-muted rounded-lg bg-[#161922]',
        "desktop store filter hide")

    # Mobile store filter row: hide
    html = html.replace(
        '<div class="md:hidden flex flex-wrap gap-2 mb-4">',
        '<div class="hidden">',
    )

    # --- 10. Add store filter dropdown to master reports ---
    master_store_dropdown = """<select x-model="masterStore" @change="loadMasterReport()"
                class="px-3 py-2.5 md:py-1.5 text-sm border border-muted rounded-lg bg-[#161922] text-[#cbd5e1] focus:outline-none focus:border-gold">
          <option value="">All Stores</option>
          <template x-for="s in stores" :key="s">
            <option :value="s" x-text="s.replace('Thrive Cannabis ','').replace('Thrive ','')"></option>
          </template>
        </select>"""
    html = _checked_replace(html,
        '<div class="sm:ml-auto flex items-center gap-2">',
        master_store_dropdown + '\n        <div class="sm:ml-auto flex items-center gap-2">',
        "master store dropdown")

    # --- 11. Pass masterStore in loadMasterReport ---
    html = _checked_replace(html,
        "try { this.masterData = this._normalizeMaster(await this.api('/api/master/'+this.masterTab, this.periodParams()), this.masterTab); }",
        "const mp = this.periodParams(); if (this.masterStore) mp.store = this.masterStore;\n      try { this.masterData = this._normalizeMaster(await this.api('/api/master/'+this.masterTab, mp), this.masterTab); }",
        "masterStore in loadMasterReport")

    # --- 12. Remove Excel download links in master reports ---
    # Replace the download buttons container with empty div
    html = re.sub(
        r'<div class="flex gap-2">\s*<a :href="[^"]*master/\' \+ masterTab \+ \'/excel[^"]*"[^>]*>.*?Download.*?</a>\s*<a :href="[^"]*master/suite/excel[^"]*"[^>]*>.*?Download All.*?</a>\s*</div>',
        '<!-- Excel downloads removed in static mode -->',
        html,
        flags=re.DOTALL,
    )

    # --- 13. Simplify period picker: force single-month only ---
    html = _checked_replace(html,
        "this.periodType = 'range';",
        "this.periodType = 'month'; // range disabled in static mode",
        "range period type")

    # --- 14. Add init() guard to prevent double initialization ---
    html = _checked_replace(html,
        "async init() {\n      // Each call catches independently",
        "async init() {\n      if (this._initialized) return;\n      this._initialized = true;\n      // Each call catches independently",
        "init guard")

    # --- 15. Fix _c() chart function: use Chart.getChart for proper cleanup ---
    html = html.replace(
        "if (this._charts[id]) { this._charts[id].destroy(); delete this._charts[id]; }",
        "if (this._charts[id]) { try { this._charts[id].destroy(); } catch(e){} delete this._charts[id]; }",
    )
    # Add Chart.getChart cleanup before creating new chart
    html = html.replace(
        "self._charts[id] = new Chart(el, config);",
        "const existing = Chart.getChart(el); if (existing) existing.destroy();\n          self._charts[id] = new Chart(el, config);",
    )
    # Use setTimeout instead of requestAnimationFrame for chart rendering
    html = html.replace(
        "requestAnimationFrame(tryRender);",
        "setTimeout(tryRender, 300);",
    )

    # --- 16. (Removed — MoM now uses x-show in source) ---

    # --- 17. MoM always loads all-time data (comparing single months is pointless) ---
    html = html.replace(
        "this.momData = await this.api('/api/month-over-month', this.periodParams())",
        "this.momData = await this.api('/api/month-over-month', {period_type: 'all'})",
    )

    out.write_text(html)
    print(f"  Generated {out}")


def cmd_export(args):
    """Export pre-computed static site to output directory."""
    from app.analytics.dashboard import (
        executive_summary, month_over_month, store_performance, year_end_summary,
    )
    from app.config import INTERNAL_BRANDS

    print("\n" + "=" * 70)
    print("  THRIVE ANALYTICS — STATIC SITE EXPORT")
    print("=" * 70)
    print(f"  Started: {datetime.now():%Y-%m-%d %H:%M:%S}")

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    # Load data
    store = DataStore().load()
    brands = store.brands()
    periods = store.periods_available()
    years = sorted(set(p["year"] for p in periods))

    print(f"  {store.row_count():,} rows, {len(store.stores())} stores, {len(brands)} brands, {len(periods)} periods")
    print(f"  Output: {out.resolve()}\n")

    # Build brand slug mapping
    slugs = {}
    used_slugs = {}
    for b in brands:
        s = _brand_slug(b)
        if s in used_slugs:
            i = 2
            while f"{s}-{i}" in used_slugs:
                i += 1
            s = f"{s}-{i}"
        used_slugs[s] = b
        slugs[b] = s

    # --- Meta files ---
    print("  [1/6] Meta files...")
    _write_json(out / "data/health.json", {
        "status": "ok",
        "rows": store.row_count(),
        "regular_rows": store.regular_count(),
        "stores": len(store.stores()),
        "brands": len(brands),
        "periods": len(periods),
    })
    _write_json(out / "data/brands.json", {
        "brands": brands,
        "count": len(brands),
        "internal_brands": [b for b in brands if b.upper() in INTERNAL_BRANDS],
        "brand_slugs": slugs,
    })
    _write_json(out / "data/stores.json", {"stores": store.stores()})
    _write_json(out / "data/periods.json", {"periods": periods})

    # --- Dashboard views for each period ---
    print("  [2/6] Dashboard views (exec, mom, store-perf)...")
    period_filters = [None]  # None = all-time
    for p in periods:
        period_filters.append(PeriodFilter(
            period_type=PeriodType.MONTH, year=p["year"], month=p["month"],
        ))

    for i, pf in enumerate(period_filters):
        key = _period_key(pf)
        label = f"all-time" if pf is None else key
        print(f"    [{i+1}/{len(period_filters)}] {label}")
        _write_json(out / f"data/exec/{key}.json", executive_summary(store, pf))
        _write_json(out / f"data/mom/{key}.json", month_over_month(store, pf))
        _write_json(out / f"data/stores-perf/{key}.json", store_performance(store, pf))

    # --- Year-end summaries ---
    print("  [3/6] Year-end summaries...")
    for y in years:
        print(f"    {y}")
        _write_json(out / f"data/yearend/{y}.json", year_end_summary(store, y))

    # --- Brand reports (all-time) ---
    print(f"  [4/6] Brand reports ({len(brands)} brands)...")
    from app.reports.brand_dispensary import generate_json as brand_disp_json
    from app.reports.brand_facing import generate_json as brand_face_json

    skipped = 0
    for i, brand in enumerate(brands, 1):
        if i % 25 == 0 or i == len(brands):
            print(f"    [{i}/{len(brands)}]")
        slug = slugs[brand]
        try:
            brand_df = store.get_brand(brand, None)
            if len(brand_df) < 5:
                skipped += 1
                continue
            report = brand_disp_json(store, brand, None, None)
            _write_json(out / f"data/brands/{slug}/report.json", report)
        except Exception as e:
            print(f"    WARNING: {brand} dispensary report failed: {e}")
        try:
            facing = brand_face_json(store, brand, None)
            _write_json(out / f"data/brands/{slug}/facing.json", facing)
        except Exception as e:
            pass  # facing reports may fail for small brands
    if skipped:
        print(f"    ({skipped} brands skipped — fewer than 5 transactions)")

    # --- Per-year brand reports ---
    print(f"  [4b/6] Per-year brand reports ({len(brands)} brands × {len(years)} years)...")
    year_skipped = 0
    year_written = 0
    for y in years:
        year_pf = PeriodFilter(period_type=PeriodType.YEAR, year=y)
        for brand in brands:
            slug = slugs[brand]
            try:
                brand_df = store.get_brand(brand, year_pf)
                if len(brand_df) < 5:
                    year_skipped += 1
                    continue
                report = brand_disp_json(store, brand, year_pf, None)
                _write_json(out / f"data/brands/{slug}/report-{y}.json", report)
                year_written += 1
            except Exception as e:
                pass
            try:
                facing = brand_face_json(store, brand, year_pf)
                _write_json(out / f"data/brands/{slug}/facing-{y}.json", facing)
            except Exception:
                pass
        print(f"    {y}: done")
    print(f"    {year_written} year-files written, {year_skipped} skipped")

    # --- Master reports (all-time + per-store) ---
    print("  [5/6] Master reports...")
    import importlib
    master_modules = {
        "margin": "app.reports.margin_report",
        "deals": "app.reports.deal_report",
        "budtenders": "app.reports.budtender_report",
        "customers": "app.reports.customer_report",
        "rewards": "app.reports.rewards_report",
    }
    store_names = store.stores()
    store_slugs = {s: _brand_slug(s) for s in store_names}
    # Write store slug mapping into stores.json for frontend lookup
    _write_json(out / "data/stores.json", {
        "stores": store_names,
        "store_slugs": store_slugs,
    })
    for tab, mod_path in master_modules.items():
        mod = importlib.import_module(mod_path)
        # All-stores version
        try:
            data = mod.generate_json(store, None)
            _write_json(out / f"data/master/{tab}.json", data)
            print(f"    {tab}.json")
        except Exception as e:
            print(f"    WARNING: {tab} failed: {e}")
            _write_json(out / f"data/master/{tab}.json", {"error": str(e)})
        # Per-store versions
        for sname in store_names:
            slug = store_slugs[sname]
            try:
                pf = PeriodFilter(period_type=PeriodType.ALL, store=sname)
                data = mod.generate_json(store, pf)
                _write_json(out / f"data/master/{tab}/{slug}.json", data)
            except Exception as e:
                print(f"    WARNING: {tab}/{slug} failed: {e}")
                _write_json(out / f"data/master/{tab}/{slug}.json", {"error": str(e)})
        print(f"      + {len(store_names)} store files")

    # --- Copy static assets + generate patched index.html ---
    print("  [6/6] Static assets + index.html...")
    static_dir = Path(__file__).parent / "static"
    for asset in ["chart.min.js", "logo.png"]:
        src = static_dir / asset
        if src.exists():
            shutil.copy2(src, out / asset)

    _generate_static_index(out / "index.html")

    # Summary
    file_count = sum(1 for _ in out.rglob("*.json"))
    total_size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"\n  Done! {file_count} JSON files, {total_size / 1024 / 1024:.1f} MB total")
    print(f"  Output: {out.resolve()}")
    print(f"\n  Next steps:")
    print(f"    1. Test:  python3 -m http.server 8080 -d {out}")
    print(f"    2. Push:  git add {out} vercel.json && git push")
    print(f"    3. Deploy on Vercel → connect repo, set output dir to '{out}'")
    print("=" * 70 + "\n")


def cmd_serve(args):
    """Start the API server."""
    import uvicorn
    print(f"\nStarting Thrive Analytics API on port {args.port}...")
    uvicorn.run("app.main:app", host="0.0.0.0", port=args.port, reload=args.reload,
                timeout_keep_alive=65)


def main():
    parser = argparse.ArgumentParser(
        description="Thrive Analytics — Cannabis retail analytics engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # brand subcommand
    brand_parser = subparsers.add_parser("brand", help="Generate brand reports")
    brand_parser.add_argument("brands", nargs="*", help="Brand name(s)")
    brand_parser.add_argument("--list", action="store_true", help="List brands")
    brand_parser.add_argument("--top", type=int, help="Top N brands by revenue")
    brand_parser.add_argument("--facing", nargs="*", help="Generate brand-facing report(s)")
    brand_parser.add_argument("--period", choices=["month", "quarter", "year"], help="Period type")
    brand_parser.add_argument("--year", type=int, help="Year")
    brand_parser.add_argument("--month", type=int, help="Month (1-12)")
    brand_parser.add_argument("--quarter", type=int, help="Quarter (1-4)")
    brand_parser.set_defaults(func=cmd_brand)

    # master subcommand
    master_parser = subparsers.add_parser("master", help="Generate master suite")
    master_parser.add_argument("--period", choices=["month", "quarter", "year"], help="Period type")
    master_parser.add_argument("--year", type=int, help="Year")
    master_parser.add_argument("--month", type=int, help="Month (1-12)")
    master_parser.add_argument("--quarter", type=int, help="Quarter (1-4)")
    master_parser.set_defaults(func=cmd_master)

    # serve subcommand
    serve_parser = subparsers.add_parser("serve", help="Start API server")
    serve_parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")), help="Port (default 8000)")
    serve_parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    serve_parser.set_defaults(func=cmd_serve)

    # export subcommand
    export_parser = subparsers.add_parser("export", help="Export static site (for Vercel)")
    export_parser.add_argument("--output", default="public", help="Output directory (default: public)")
    export_parser.set_defaults(func=cmd_export)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()

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
"""
from __future__ import annotations

import argparse
import os
import sys
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
        brand_rev = regular.groupby("brand_clean")["actual_revenue"].sum().sort_values(ascending=False)
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


def cmd_serve(args):
    """Start the API server."""
    import uvicorn
    print(f"\nStarting Thrive Analytics API on port {args.port}...")
    uvicorn.run("app.main:app", host="0.0.0.0", port=args.port, reload=args.reload)


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

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()

# server.py
from pathlib import Path
import pandas as pd

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import brand_report

app = FastAPI(title="Thrive Analytics API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def build_category_lookups(regular_df: pd.DataFrame):
    cat_metrics = regular_df.groupby("category_clean").agg(
        total_revenue=("actual_revenue", "sum"),
        total_cost=("cost", "sum"),
    ).reset_index()

    cat_metrics["category_margin"] = (
        (cat_metrics["total_revenue"] - cat_metrics["total_cost"])
        / cat_metrics["total_revenue"].replace(0, pd.NA)
        * 100
    ).round(1)

    category_margin_lookup = dict(
        zip(cat_metrics["category_clean"], cat_metrics["category_margin"])
    )

    brand_cat_rev = (
        regular_df.groupby(["category_clean", "brand_clean"])["actual_revenue"]
        .sum()
        .reset_index()
    )
    brand_cat_rev["rank"] = brand_cat_rev.groupby("category_clean")["actual_revenue"].rank(
        ascending=False, method="min"
    )
    brand_cat_rev["total_brands"] = brand_cat_rev.groupby("category_clean")["brand_clean"].transform("count")

    return category_margin_lookup, brand_cat_rev


@app.post("/api/brand/export")
async def export_brand_report(
    csvFile: UploadFile = File(...),
    brandName: str = Form(...),
    storeName: str | None = Form(None),
):
    # 1) Save uploaded CSV to a REAL folder (not temp)
    base_dir = Path.home() / "Desktop" / "Thrive Analytics"
    uploads_dir = base_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    csv_path = uploads_dir / "uploaded.csv"
    csv_path.write_bytes(await csvFile.read())

    # 2) Load + filter using your existing logic
    df = brand_report.load_sales_data(csv_path)
    regular_df = df[df["is_regular"]].copy()

    # store filter (treat empty/all as no filter)
    if storeName:
        s = storeName.strip()
        if s and s.lower() not in ["all", "string", "null", "none"]:
            regular_df = regular_df[regular_df["store_clean"] == s]

    if regular_df.empty:
        raise HTTPException(400, "No valid data after filtering")

    # brand match (case-insensitive)
    brands = [str(b) for b in regular_df["brand_clean"].dropna().unique()]
    brand_match = next((b for b in brands if b.upper() == brandName.upper()), None)
    if not brand_match:
        raise HTTPException(400, f"Brand not found: {brandName}")

    brand_df = regular_df[regular_df["brand_clean"].astype(str) == brand_match].copy()
    if brand_df.empty:
        raise HTTPException(400, "No data for selected brand")

    # date range label
    dates = df["sale_date"].dropna()
    date_range = f"{dates.min()} to {dates.max()}" if len(dates) else "N/A"

    # category lookups + rankings
    category_lookup, brand_rankings = build_category_lookups(regular_df)

    # 3) Save Excel to your existing brand_reports folder
    out_dir = base_dir / "brand_reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_name = brand_match.replace("/", "-").replace("\\", "-")[:40]
    out_path = out_dir / f"Brand_Report_{safe_name}.xlsx"

    brand_report.create_brand_report(
        brand_df=brand_df,
        brand_name=brand_match,
        output_path=out_path,
        date_range=date_range,
        category_margin_lookup=category_lookup,
        brand_category_rankings=brand_rankings,
    )

    # 4) Return the file
    return FileResponse(
        path=str(out_path),
        filename=out_path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


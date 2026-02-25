#!/usr/bin/env python3
"""
Demo transformation script for Thrive Analytics.

Walks all JSON files in public/data/, renames stores from Thrive to Elevation,
inflates financial numbers, and renames store-specific files.

Usage:
    python3 scripts/demo_transform.py [--public-dir ./public]
"""

import argparse
import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# Store mapping
# ---------------------------------------------------------------------------
STORE_MAP = {
    "Thrive Cactus":      "Elevation Springs",
    "Thrive Cheyenne":    "Elevation Mesa",
    "Thrive Jackpot":     "Elevation Oasis",
    "Thrive Main Street": "Elevation Downtown",
    "Thrive Reno":        "Elevation Midtown",
    "Thrive Sahara":      "Elevation Boulevard",
    "Thrive Sammy":       "Elevation Parkway",
}

SLUG_MAP = {
    "thrive-cactus":      "elevation-springs",
    "thrive-cheyenne":    "elevation-mesa",
    "thrive-jackpot":     "elevation-oasis",
    "thrive-main-street": "elevation-downtown",
    "thrive-reno":        "elevation-midtown",
    "thrive-sahara":      "elevation-boulevard",
    "thrive-sammy":       "elevation-parkway",
}

COMPANY_MAP = {
    "Thrive Cannabis": "Elevation Cannabis",
    "Thrive Analytics": "Elevation Analytics",
}

# ---------------------------------------------------------------------------
# Field classification for inflation
# ---------------------------------------------------------------------------
# Dollar fields: multiply by 2.5x
DOLLAR_KEYWORDS = {
    "revenue", "profit", "cost", "discounts", "sales", "collected",
    "price", "basket", "cart", "spend", "value", "margin_gap",
    "savings",
}

# Count fields: multiply by 2x
COUNT_KEYWORDS = {
    "units", "transactions", "customers", "times_used", "count",
    "items",
}

# Percentage/rate fields: leave unchanged
PCT_KEYWORDS = {
    "margin", "pct", "pts", "rate", "share", "velocity", "rank",
    "ratio", "index", "score", "gap", "status", "health",
}

# Fields to never touch
SKIP_FIELDS = {
    "month", "month_num", "year", "stores", "brands", "total_brands",
    "rank", "label", "name", "brand", "category", "product", "deal_name",
    "tier", "date_range", "period_label", "action", "detail", "severity",
    "title", "category_clean", "store", "top_brand", "top_category",
    "margin_status", "deal_type", "type", "segment",
}


def classify_field(key: str) -> str:
    """Classify a JSON field as 'dollar', 'count', 'pct', or 'skip'."""
    key_lower = key.lower()

    # Explicit skip fields
    if key_lower in SKIP_FIELDS:
        return "skip"

    # Check percentage first (most specific)
    for kw in PCT_KEYWORDS:
        if kw in key_lower:
            return "pct"

    # Check dollar fields
    for kw in DOLLAR_KEYWORDS:
        if kw in key_lower:
            return "dollar"

    # Check count fields
    for kw in COUNT_KEYWORDS:
        if kw in key_lower:
            return "count"

    return "skip"


def inflate_value(value, field_type: str):
    """Apply inflation multiplier based on field type."""
    if not isinstance(value, (int, float)):
        return value
    if field_type == "dollar":
        return value * 2.5
    elif field_type == "count":
        return value * 2
    return value


# ---------------------------------------------------------------------------
# Recursive JSON transformer
# ---------------------------------------------------------------------------
def transform_value(obj, parent_key: str = ""):
    """Recursively transform a JSON value: rename stores + inflate numbers."""
    if isinstance(obj, str):
        return rename_stores_in_string(obj)

    if isinstance(obj, (int, float)) and parent_key:
        field_type = classify_field(parent_key)
        return inflate_value(obj, field_type)

    if isinstance(obj, list):
        return [transform_value(item, parent_key) for item in obj]

    if isinstance(obj, dict):
        new_dict = {}
        for k, v in obj.items():
            new_key = rename_stores_in_string(k) if isinstance(k, str) else k
            new_dict[new_key] = transform_value(v, k)
        return new_dict

    return obj


def rename_stores_in_string(s: str) -> str:
    """Replace all Thrive store/company names and slugs in a string."""
    for old, new in COMPANY_MAP.items():
        s = s.replace(old, new)
    for old, new in STORE_MAP.items():
        s = s.replace(old, new)
    for old, new in SLUG_MAP.items():
        s = s.replace(old, new)
    # Catch any remaining "Thrive " references (but not brand names like "THRIVE")
    s = s.replace("Thrive ", "Elevation ")
    return s


# ---------------------------------------------------------------------------
# File processing
# ---------------------------------------------------------------------------
def process_json_file(filepath: str) -> None:
    """Load, transform, and overwrite a single JSON file."""
    with open(filepath, "r") as f:
        data = json.load(f)

    transformed = transform_value(data)

    with open(filepath, "w") as f:
        json.dump(transformed, f, separators=(",", ":"))


def rename_store_files(public_dir: str) -> int:
    """Rename thrive-*.json files to elevation-*.json equivalents."""
    renamed = 0
    for root, dirs, files in os.walk(public_dir):
        for filename in files:
            for old_slug, new_slug in SLUG_MAP.items():
                if filename == f"{old_slug}.json":
                    old_path = os.path.join(root, filename)
                    new_path = os.path.join(root, f"{new_slug}.json")
                    os.rename(old_path, new_path)
                    renamed += 1
                    break
    return renamed


def update_index_html(public_dir: str) -> None:
    """Replace Thrive branding in index.html."""
    index_path = os.path.join(public_dir, "index.html")
    if not os.path.exists(index_path):
        print(f"  WARNING: {index_path} not found, skipping HTML update")
        return

    with open(index_path, "r") as f:
        html = f.read()

    replacements = [
        ("Thrive Analytics", "Elevation Analytics"),
        ("Thrive Cannabis", "Elevation Cannabis"),
        ("Thrive In-House Brand", "In-House Brand"),
        (".replace('Thrive Cannabis ','').replace('Thrive ','')",
         ".replace('Elevation Cannabis ','').replace('Elevation ','')"),
        ('alt="Thrive"', 'alt="Elevation"'),
    ]

    for old, new in replacements:
        html = html.replace(old, new)

    with open(index_path, "w") as f:
        f.write(html)

    print(f"  Updated {index_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Transform Thrive data for demo")
    parser.add_argument("--public-dir", default="./public",
                        help="Path to public/ directory (default: ./public)")
    args = parser.parse_args()

    public_dir = os.path.abspath(args.public_dir)
    data_dir = os.path.join(public_dir, "data")

    if not os.path.isdir(data_dir):
        print(f"ERROR: {data_dir} not found. Run export first.")
        sys.exit(1)

    # 1. Transform all JSON files (content)
    json_files = []
    for root, dirs, files in os.walk(data_dir):
        for f in files:
            if f.endswith(".json"):
                json_files.append(os.path.join(root, f))

    print(f"Transforming {len(json_files)} JSON files...")
    for i, filepath in enumerate(json_files):
        process_json_file(filepath)
        if (i + 1) % 200 == 0:
            print(f"  Processed {i + 1}/{len(json_files)} files...")
    print(f"  Done: {len(json_files)} files transformed")

    # 2. Rename store-specific files (thrive-*.json -> elevation-*.json)
    print("Renaming store-specific files...")
    renamed = rename_store_files(data_dir)
    print(f"  Renamed {renamed} files")

    # 3. Update index.html branding
    print("Updating index.html branding...")
    update_index_html(public_dir)

    # 4. Verify no Thrive references remain
    print("\nVerification:")
    thrive_count = 0
    for root, dirs, files in os.walk(public_dir):
        for f in files:
            filepath = os.path.join(root, f)
            with open(filepath, "r", errors="ignore") as fh:
                content = fh.read()
                matches = [m for m in re.finditer(r"[Tt]hrive", content)]
                if matches:
                    thrive_count += len(matches)
                    print(f"  WARNING: {len(matches)} 'Thrive' references in {filepath}")

    if thrive_count == 0:
        print("  PASS: No 'Thrive' references found in public/")
    else:
        print(f"  FAIL: {thrive_count} 'Thrive' references remain")

    print("\nDone! Spot-check with: python3 -m http.server 8080 -d public")


if __name__ == "__main__":
    main()

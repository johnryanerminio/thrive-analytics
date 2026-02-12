"""
Thrive Analytics — Configuration: paths, constants, file patterns.
"""
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths — override with THRIVE_DATA_DIR env var for cloud deployment
# ---------------------------------------------------------------------------
_data_dir = Path(os.environ.get("THRIVE_DATA_DIR", str(Path.home() / "Desktop" / "Thrive Analytics")))
BASE_FOLDER = _data_dir
INBOX_FOLDER = _data_dir / "inbox"
ARCHIVE_FOLDER = _data_dir / "archive"
REPORTS_FOLDER = _data_dir / "reports"
BRAND_REPORTS_FOLDER = _data_dir / "brand_reports"
UPLOADS_FOLDER = _data_dir / "uploads"
SHARES_FOLDER = _data_dir / "shares"

# ---------------------------------------------------------------------------
# File-discovery patterns (keywords matched case-insensitively in filename)
# ---------------------------------------------------------------------------
SALES_KEYWORDS = ["margin", "line_item", "john"]
BT_PERFORMANCE_KEYWORDS = ["bt sales", "bt_sales", "budtender"]
CUSTOMER_KEYWORDS = ["customer"]

# ---------------------------------------------------------------------------
# Column mapping from raw Flowhub CSV → internal names
# ---------------------------------------------------------------------------
COLUMN_MAP = {
    "Receipt ID": "receipt_id",
    "Order Type": "order_type",
    "Sold By": "sold_by",
    "Completed At": "completed_at",
    "Customer ID": "customer_id",
    "Customer Name": "customer_name",
    "Store": "store",
    "Product": "product",
    "Variant Type": "category",
    "Brand": "brand",
    "Quantity Sold": "quantity",
    "Pre-Discount, Pre-Tax Total": "pre_discount_revenue",
    "Discounts": "discounts",
    "Taxes": "taxes",
    "Post-Discount, Pre-Tax Total": "actual_revenue",
    "Total Collected (Post-Discount, Post-Tax, Post-Fees)": "total_collected",
    "Receipt Total Collected": "receipt_total",
    "Net Profit": "net_profit",
    "Cost": "cost",
    "Cost Per Item": "cost_per_item",
    "Deals Used": "deals_used",
    "Inline/Cart Discounts Used": "inline_discounts",
}

CURRENCY_COLS = [
    "pre_discount_revenue",
    "discounts",
    "actual_revenue",
    "net_profit",
    "cost",
    "total_collected",
    "receipt_total",
    "cost_per_item",
    "taxes",
]

# ---------------------------------------------------------------------------
# Category normalization map
# ---------------------------------------------------------------------------
CATEGORY_NORMALIZATION = {
    "ACCESSORY": "ACCESSORY",
    "PRE-ROLL": "PRE ROLL",
    "PREROLL": "PRE ROLL",
    "PRE-ROLLS": "PRE ROLL",
    "PRE ROLLS": "PRE ROLL",
    "PRE-ROLL PACK": "PRE ROLL PACK",
    "PREROLL PACK": "PRE ROLL PACK",
    "VAPE": "CARTRIDGE",
    "CART": "CARTRIDGE",
    "CARTS": "CARTRIDGE",
    "DISPOSABLE": "DISPOSABLE VAPE",
    "DISPO": "DISPOSABLE VAPE",
    "GUMMY": "EDIBLE",
    "GUMMIES": "EDIBLE",
    "EDIBLES": "EDIBLE",
}

# ---------------------------------------------------------------------------
# Customer segment keywords (order matters — first match wins)
# ---------------------------------------------------------------------------
CUSTOMER_SEGMENTS = [
    ("INDUSTRY", "Industry"),
    ("EMPLOYEE", "Employee"),
    ("VETERAN", "Veteran"),
    ("MILITARY", "Veteran"),
    ("SENIOR", "Senior"),
    ("VIP", "VIP"),
    ("MEDICAL", "Medical"),
    ("MED", "Medical"),
    ("LOCAL", "Locals"),
]

# ---------------------------------------------------------------------------
# Share link defaults
# ---------------------------------------------------------------------------
SHARE_EXPIRY_DAYS = 30

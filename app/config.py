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
SALES_KEYWORDS = ["margin", "line_item", "john", "sales performance"]
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
# Internal brand cost correction
# Flowhub cost data is unreliable for these house brands:
#   - 2024: costs were $0 or pennies
#   - 2025: costs were inflated/inaccurate
#   - 2026: HAUS and H&G costs confirmed at $6.62; Pistola/G&G also corrected
# ---------------------------------------------------------------------------
INTERNAL_BRAND_COSTS = {
    "HAUS":         {"default": 6.62, "pre_roll": 4.00},
    "HUSTLE & GROW": {"default": 6.62, "pre_roll": 4.00},
    "PISTOLA":      {"default": 8.63,  "pre_roll": 4.00},
    "GREEN & GOLD": {"default": 8.63,  "pre_roll": 4.00},
    "FADE":         {"cart": 10.61, "disposable": 12.44},
    "RETREAT":      {"cart": 10.61, "disposable": 12.44},
    "SRENE":        {"cart": 10.76, "flower_eighth": 13.00, "flower_half_oz": 25.00},
}

FLOWER_CATEGORIES = {"FLOWER"}
FLOWER_HALF_OZ_KEYWORDS = {"HALF OUNCE", "HALF OZ", "14G"}

# "conditional" = only replace when cost_per_item < $1
# "unconditional" = replace ALL costs regardless of current value
# Uses defaultdict so new years are automatically corrected
from collections import defaultdict
COST_CORRECTION_YEARS = defaultdict(lambda: "unconditional", {
    2024: "unconditional",
    2025: "unconditional",
    2026: "unconditional",
})

PRE_ROLL_CATEGORIES = {"PRE ROLL", "PRE ROLL PACK"}
CART_CATEGORIES = {"CARTRIDGE"}
DISPOSABLE_CATEGORIES = {"DISPOSABLE VAPE"}

# ---------------------------------------------------------------------------
# In-house brand names (for visual indicators in the UI)
# Superset of INTERNAL_BRAND_COSTS — includes brands without cost corrections
# ---------------------------------------------------------------------------
INTERNAL_BRANDS = {
    "HAUS", "HUSTLE & GROW", "PISTOLA", "GREEN & GOLD",
    "RETREAT", "FADE", "G&G EXTRACTS",
}

# ---------------------------------------------------------------------------
# Excluded stores (hidden from dashboard — negligible/test locations)
# ---------------------------------------------------------------------------
EXCLUDED_STORES = {"Thrive Commerce"}

# ---------------------------------------------------------------------------
# Share link defaults
# ---------------------------------------------------------------------------
SHARE_EXPIRY_DAYS = 30

# ---------------------------------------------------------------------------
# Business-rule thresholds (centralized for easy tuning)
# ---------------------------------------------------------------------------

# Sales mix health — full-price percentage thresholds
SALES_MIX_HEALTHY_PCT = 35
SALES_MIX_WATCH_PCT = 25

# Margin thresholds for dashboard insights
MARGIN_EXCELLENT_PCT = 55
MARGIN_BELOW_TARGET_PCT = 40
DISCOUNT_DEPENDENCY_PCT = 30
MARGIN_GAP_SIGNIFICANT_PTS = 15

# Recommendation thresholds
REC_MARGIN_VS_CAT_GAP_PTS = -5
REC_PROMO_DEPENDENCY_PCT = 25
REC_LOW_DISC_MARGIN_PCT = 35
REC_VOLUME_LEVERAGE_REVENUE = 5000
REC_HIGH_PRIORITY_CATEGORY_REVENUE = 10000

# Budtender scoring weights (must sum to 100)
BT_WEIGHT_CART = 30
BT_WEIGHT_UNITS = 25
BT_WEIGHT_DISCOUNT = 20
BT_WEIGHT_LOYALTY = 15
BT_WEIGHT_F2F = 10

# Budtender tier thresholds
BT_TIER_TOP = 70
BT_TIER_SOLID = 50
BT_TIER_DEVELOPING = 30

# ---------------------------------------------------------------------------
# Monthly Operating Expenses (for EBITDA proxy calculation)
# These are TOTAL monthly figures across all stores.
# Update with actuals from your CFO — placeholder zeros until then.
# ---------------------------------------------------------------------------
MONTHLY_OPEX = {
    "labor": 0,              # total monthly payroll + benefits
    "rent": 0,               # total monthly rent / occupancy
    "utilities": 0,          # utilities, insurance, misc operating
    "other_opex": 0,         # other operating expenses
    "depreciation": 0,       # monthly depreciation & amortization (added back for EBITDA)
}
OPEX_CONFIGURED = any(v > 0 for v in MONTHLY_OPEX.values())

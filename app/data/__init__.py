"""Data loading, normalization, and in-memory query engine."""
from .loader import discover_csvs, load_all_csvs
from .store import DataStore
from .schemas import PeriodFilter
from .normalize import normalize_columns, normalize_categories, classify_transaction, classify_deal_type

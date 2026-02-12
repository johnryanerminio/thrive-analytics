# 🌿 Thrive Cannabis - Master Analytics Suite

## Overview
This automation package generates **5 professional Excel reports** from your Flowhub POS data with a single command.

## Reports Generated

| Report | Sheets | Description |
|--------|--------|-------------|
| **Margin_Report.xlsx** | 5 | Full Price vs Discounted Sales analysis with TOTAL rows |
| **Deal_Performance_Report.xlsx** | 4 | Deal classification, Top 50 deals, by Store/Brand |
| **Budtender_Performance_Report.xlsx** | 8+ | Sales Score (0-100), Face-to-Face %, by Store |
| **Customer_Insights_Report.xlsx** | 10+ | Segments, Loyalty, Top 50 customers by Store |
| **Rewards_Markout_Report.xlsx** | 5 | Program costs with Store and Product details |

## Quick Start

### 1. Setup Folder Structure
The script will automatically create this structure:
```
~/Desktop/Thrive Analytics/
├── inbox/          ← Drop your CSV files here
├── archive/        ← Processed files move here
└── reports/        ← Generated reports saved here
    └── 20260105_093000/   ← Timestamped folders
```

### 2. Required Input Files
Export these 3 reports from Flowhub and drop them in the `inbox` folder:

| File | Naming Pattern |
|------|---------------|
| **Margin Report** | Any file with "margin" or "john" in name |
| **BT Sales Performance** | Any file with "bt" or "budtender" in name |
| **Customer Sales Performance** | Any file with "customer" in name |

### 3. Run the Script
```bash
python thrive_analytics_master.py
```

### 4. Output
- All 5 reports generated in `~/Desktop/Thrive Analytics/reports/[timestamp]/`
- Input files automatically archived
- Console shows executive summary

## Key Metrics

### Margin Report
- **Full Price Sales** vs **Discounted Sales** breakdown
- **% at Full Price** - how much business is at full price
- **Full Price Margin** vs **Discounted Margin** vs **Blended Margin**
- **Margin Gap** - the cost of discounting in margin points

### Budtender Performance
- **Sales Score (0-100)** - composite ranking based on:
  - Cart value (30%)
  - Units per cart (25%)
  - Discount discipline (20%)
  - Loyalty enrollments (15%)
  - Face-to-face sales (10%)
- **Performance Tiers**: Top Performer (70+), Solid (50-69), Developing (30-49), Needs Coaching (<30)

### Customer Insights
- **Segments**: Industry, Employee, Veteran, Senior, VIP, Medical, Locals, LVAC, Regular
- **Top 50 by Store** - individual VIP lists per location
- **Revenue per Customer** - customer value analysis

### Rewards & Markout
- **Net Cost** = Product Cost - Amount Collected
- **Monthly/Annual Projections** - scaled from sample period
- **By Employee** - includes Store and Products marked out

## Customization

Edit the `CONFIG` dictionary in `thrive_analytics_master.py`:

```python
CONFIG = {
    'base_folder': Path.home() / 'Desktop' / 'Thrive Analytics',
    'file_patterns': {
        'sales': ['margin', 'line_item', 'john'],
        'bt_performance': ['bt sales', 'bt_sales', 'budtender'],
        'customers': ['customer'],
    }
}
```

## Requirements
- Python 3.8+
- pandas
- openpyxl
- numpy

Install with:
```bash
pip install pandas openpyxl numpy
```

## Support
This package was built for Thrive Cannabis Nevada operations. For questions or enhancements, contact your analytics team.

---
*Generated: January 2026*

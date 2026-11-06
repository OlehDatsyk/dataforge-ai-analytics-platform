"""Generate the synthetic demonstration datasets in sample_datasets/.

Every value comes from a seeded random generator, with no real people, companies, or transactions.
Data quality problems and unusual values are planted deliberately so the features have something to find.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parents[2] / "sample_datasets"
PRODUCTS = {
    "Electronics": [("Aurora Headphones", 129), ("Nimbus Speaker", 89), ("Vertex Tablet", 349), ("Quill E-Reader", 119), ("Pulse Smartwatch", 199)],
    "Home": [("Hearth Kettle", 45), ("Lumen Desk Lamp", 39), ("Willow Throw", 55), ("Cedar Storage Set", 72)],
    "Office": [("Atlas Notebook", 12), ("Ridge Monitor Stand", 49), ("Scribe Pen Set", 18), ("Summit Chair Cushion", 34)],
    "Outdoor": [("Trail Backpack", 79), ("Ember Camp Stove", 95), ("Harbor Water Bottle", 22), ("Canyon Tent", 210)],
}
COUNTRIES = {"North America": ["United States", "Canada"], "Europe": ["United Kingdom", "Germany", "France"], "Asia Pacific": ["Japan", "Australia"], "Latin America": ["Brazil", "Mexico"]}


def retail(rng: np.random.Generator) -> pd.DataFrame:
    days = pd.date_range("2023-01-01", "2024-12-31", freq="D")
    day_of_year = np.asarray(days.day_of_year, dtype=float)
    season = 1 + 0.25 * np.sin(2 * np.pi * (day_of_year - 80) / 365) + np.where(np.isin(days.month, [11, 12]), 0.45, 0)
    growth = 1 + 0.18 * (np.arange(len(days)) / len(days))
    weights = np.asarray(season * growth, dtype=float)
    dates = rng.choice(days, size=6000, p=weights / weights.sum())
    dates = np.sort(dates)
    rows = []
    categories = list(PRODUCTS)
    regions = list(COUNTRIES)
    for i, day in enumerate(dates):
        category = rng.choice(categories, p=[0.38, 0.24, 0.2, 0.18])
        names = PRODUCTS[category]
        product, base = names[rng.integers(len(names))]
        region = rng.choice(regions, p=[0.42, 0.33, 0.17, 0.08])
        country = rng.choice(COUNTRIES[region])
        quantity = int(rng.integers(1, 6))
        price = round(base * rng.uniform(0.92, 1.08), 2)
        discount = float(rng.choice([0, 0, 0, 5, 10, 15, 20]))
        revenue = round(quantity * price * (1 - discount / 100), 2)
        cost = round(revenue * rng.uniform(0.52, 0.74), 2)
        rows.append({
            "order_id": f"ORD-{100000 + i}",
            "order_date": pd.Timestamp(day).strftime("%Y-%m-%d"),
            "region": region,
            "country": country,
            "category": category,
            "product": product,
            "customer_segment": rng.choice(["Consumer", "Small Business", "Enterprise"], p=[0.62, 0.28, 0.1]),
            "sales_channel": rng.choice(["Online", "Retail Store", "Partner"], p=[0.55, 0.33, 0.12]),
            "quantity": quantity,
            "unit_price": price,
            "discount_pct": discount,
            "revenue": revenue,
            "cost": cost,
        })
    frame = pd.DataFrame(rows)
    # Planted issues: bulk orders, missing discounts, varied labels, and duplicate rows.
    bulk = rng.choice(frame.index, 12, replace=False)
    frame.loc[bulk, "quantity"] = rng.integers(180, 420, 12)
    frame.loc[bulk, "revenue"] = (frame.loc[bulk, "quantity"] * frame.loc[bulk, "unit_price"]).round(2)
    frame["discount_pct"] = frame["discount_pct"].astype(object)
    frame.loc[rng.choice(frame.index, 180, replace=False), "discount_pct"] = None
    frame.loc[rng.choice(frame.index, 40, replace=False), "sales_channel"] = "online"
    frame.loc[rng.choice(frame.index, 25, replace=False), "country"] = " Germany "
    return pd.concat([frame, frame.sample(30, random_state=7)], ignore_index=True).sort_values("order_date", kind="stable")


def customers(rng: np.random.Generator) -> pd.DataFrame:
    n = 2500
    signup = pd.Timestamp("2022-01-01") + pd.to_timedelta(rng.integers(0, 1000, n), unit="D")
    tenure = rng.integers(1, 48, n)
    frame = pd.DataFrame({
        "customer_id": [f"CUST-{20000 + i}" for i in range(n)],
        "signup_date": signup.strftime("%Y-%m-%d"),
        "country": rng.choice(["United Kingdom", "United States", "Germany", "Canada", "Australia", "France"], n, p=[0.24, 0.32, 0.14, 0.12, 0.1, 0.08]),
        "plan": rng.choice(["Free", "Starter", "Growth", "Scale"], n, p=[0.35, 0.33, 0.24, 0.08]),
        "age": rng.normal(39, 11, n).clip(18, 80).round().astype(int),
        "tenure_months": tenure,
        "orders": rng.poisson(6, n) + 1,
        "lifetime_value": np.round(rng.lognormal(5.2, 0.8, n) * (1 + tenure / 40), 2),
        "satisfaction_score": np.round(rng.normal(7.4, 1.5, n).clip(1, 10), 1),
        "churned": rng.choice(["yes", "no"], n, p=[0.21, 0.79]),
    })
    frame["satisfaction_score"] = frame["satisfaction_score"].astype(object)
    frame.loc[rng.choice(frame.index, 210, replace=False), "satisfaction_score"] = None
    return frame


def traffic(rng: np.random.Generator) -> pd.DataFrame:
    days = pd.date_range("2024-01-01", "2024-12-31", freq="D")
    channels = {"Organic Search": 4200, "Paid Search": 1800, "Email": 700, "Social": 1100, "Direct": 1500}
    rows = []
    for day in days:
        weekly = 0.82 if day.day_of_week >= 5 else 1.06
        for channel, base in channels.items():
            sessions = int(rng.normal(base * weekly * (1 + day.day_of_year / 1500), base * 0.06))
            if pd.Timestamp("2024-08-12") <= day <= pd.Timestamp("2024-08-14"):
                sessions = int(sessions * 0.22)  # planted outage
            if channel == "Email" and day == pd.Timestamp("2024-11-29"):
                sessions = int(sessions * 7)  # planted campaign spike
            conversions = int(sessions * rng.uniform(0.012, 0.031))
            rows.append({
                "date": day.strftime("%Y-%m-%d"),
                "channel": channel,
                "device": rng.choice(["Desktop", "Mobile", "Tablet"], p=[0.44, 0.5, 0.06]),
                "sessions": sessions,
                "pageviews": int(sessions * rng.uniform(2.1, 3.4)),
                "bounce_rate": round(rng.uniform(0.34, 0.62), 3),
                "conversions": conversions,
            })
    return pd.DataFrame(rows)


def finance(rng: np.random.Generator) -> pd.DataFrame:
    n = 8000
    dates = pd.Timestamp("2024-01-01") + pd.to_timedelta(np.sort(rng.integers(0, 366 * 24 * 60, n)), unit="min")
    categories = {"Groceries": 62, "Travel": 340, "Utilities": 120, "Software": 95, "Dining": 48, "Equipment": 410, "Payroll Services": 780}
    names = list(categories)
    category = rng.choice(names, n, p=[0.28, 0.1, 0.12, 0.14, 0.24, 0.07, 0.05])
    amounts = np.array([rng.lognormal(np.log(categories[c]), 0.45) for c in category]).round(2)
    frame = pd.DataFrame({
        "transaction_id": [f"TX-{500000 + i}" for i in range(n)],
        "timestamp": dates.strftime("%Y-%m-%d %H:%M:%S"),
        "account": rng.choice([f"ACC-{i:03d}" for i in range(1, 41)], n),
        "merchant_category": category,
        "merchant": [f"Sample Merchant {rng.integers(1, 90):02d}" for _ in range(n)],
        "payment_method": rng.choice(["Card", "Bank Transfer", "Direct Debit"], n, p=[0.68, 0.2, 0.12]),
        "amount": amounts,
        "currency": "USD",
        "status": rng.choice(["Settled", "Pending", "Reversed"], n, p=[0.94, 0.04, 0.02]),
    })
    frame.loc[rng.choice(frame.index, 15, replace=False), "amount"] = rng.uniform(25000, 90000, 15).round(2)
    frame["merchant"] = frame["merchant"].astype(object)
    # Planted pattern: merchant names are missing during one week of March.
    march = frame["timestamp"].str.startswith(("2024-03-11", "2024-03-12", "2024-03-13", "2024-03-14", "2024-03-15"))
    frame.loc[march & (rng.random(n) < 0.6), "merchant"] = None
    return frame


def products(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for i in range(400):
        category = rng.choice(list(PRODUCTS))
        base = PRODUCTS[category][rng.integers(len(PRODUCTS[category]))]
        price = round(base[1] * rng.uniform(0.7, 1.4), 2)
        units = int(rng.lognormal(5.5, 0.9))
        returns = int(units * rng.uniform(0.005, 0.09))
        rows.append({
            "product_id": f"PRD-{3000 + i}",
            "product_name": f"{base[0]} Mk{rng.integers(1, 9)}",
            "category": category,
            "launch_date": (pd.Timestamp("2020-01-01") + pd.Timedelta(days=int(rng.integers(0, 1700)))).strftime("%Y-%m-%d"),
            "unit_price": price,
            "units_sold": units,
            "revenue": round(price * units, 2),
            "returns": returns,
            "return_rate": round(returns / max(units, 1), 4),
            "average_rating": round(float(rng.normal(4.1, 0.45)), 2),
            "stock_on_hand": int(rng.integers(0, 2200)),
        })
    frame = pd.DataFrame(rows)
    frame.loc[rng.choice(frame.index, 6, replace=False), "return_rate"] = rng.uniform(0.3, 0.55, 6).round(4)
    return frame


def main() -> None:
    OUT.mkdir(exist_ok=True)
    generators = {
        "retail_sales.csv": retail,
        "customer_analytics.csv": customers,
        "website_traffic.csv": traffic,
        "financial_transactions.csv": finance,
        "product_performance.csv": products,
    }
    for filename, generator in generators.items():
        frame = generator(np.random.default_rng(20241))
        frame.to_csv(OUT / filename, index=False, lineterminator="\n")
        print(f"{filename}: {len(frame):,} rows, {frame.shape[1]} columns")


if __name__ == "__main__":
    main()

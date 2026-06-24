"""Generate a deterministic, SAP-like raw order-process event log.

This script simulates raw event data exported from an SAP-like operational
system.  It intentionally includes regional timing differences, priority
orders, and varying order quantities for process-mining practice.
"""

from datetime import datetime, timedelta
from pathlib import Path
import random

import pandas as pd


random.seed(42)

ACTIVITIES = [
    "Order Created",
    "Order Approved",
    "Production Started",
    "Quality Check",
    "Shipping Started",
    "Delivered",
]
REGIONS = ["DE", "US", "CN", "BR", "IN"]


def waiting_hours(region: str, activity_index: int, priority: str) -> float:
    """Return a plausible delay before the next process activity."""
    # German orders generally move through the process more quickly.
    regional_factor = {"DE": 0.75, "US": 1.0, "CN": 1.1, "BR": 1.15, "IN": 1.05}[region]
    base_hours = [3, 18, 30, 10, 36][activity_index]
    delay = random.uniform(base_hours * 0.55, base_hours * 1.35) * regional_factor

    # CN and BR occasionally experience a long approval-to-production wait.
    if activity_index == 1 and region in {"CN", "BR"} and random.random() < 0.28:
        delay += random.uniform(48, 120)

    # High-priority orders are expedited after creation.
    if priority == "High":
        delay *= 0.7

    return round(delay, 2)


def generate_event_log(order_count: int = 600) -> pd.DataFrame:
    """Create six chronologically ordered event rows for each order."""
    rows = []
    start_date = datetime(2025, 1, 1, 8, 0, 0)

    for order_number in range(1, order_count + 1):
        region = random.choice(REGIONS)
        priority = "High" if random.random() < 0.15 else "Normal"
        quantity = random.randint(250, 1000) if random.random() < 0.12 else random.randint(10, 250)
        case_id = f"ORD-{order_number:04d}"
        current_time = start_date + timedelta(
            days=random.randint(0, 180), hours=random.randint(0, 9), minutes=random.randint(0, 59)
        )

        order_attributes = {
            "case_id": case_id,
            "region": region,
            "customer": f"CUST-{region}-{random.randint(1000, 9999)}",
            "material_id": f"MAT-{random.randint(10000, 10099)}",
            "quantity": quantity,
            "priority": priority,
        }

        for activity_index, activity in enumerate(ACTIVITIES):
            rows.append({**order_attributes, "activity": activity, "timestamp": current_time})
            if activity_index < len(ACTIVITIES) - 1:
                current_time += timedelta(hours=waiting_hours(region, activity_index, priority))

    return pd.DataFrame(rows)[
        ["case_id", "activity", "timestamp", "region", "customer", "material_id", "quantity", "priority"]
    ]


def main() -> None:
    event_log = generate_event_log()
    output_path = Path(__file__).resolve().parents[1] / "data" / "raw" / "event_log.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    event_log.to_csv(output_path, index=False, date_format="%Y-%m-%d %H:%M:%S")
    print(f"Generated {len(event_log)} rows for {event_log['case_id'].nunique()} orders: {output_path}")


if __name__ == "__main__":
    main()

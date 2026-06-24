"""Run a simplified process-conformance check on the cleaned event log."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pandas as pd


EXPECTED_SEQUENCE = [
    "Order Created",
    "Order Approved",
    "Production Started",
    "Quality Check",
    "Shipping Started",
    "Delivered",
]


def ordered_steps(steps: set[str]) -> list[str]:
    """Return process steps in the business-defined process order."""
    return [activity for activity in EXPECTED_SEQUENCE if activity in steps]


def main() -> None:
    """Compare each case with the expected SAP-like order-process sequence.

    This is a simplified process-conformance analysis inspired by process-mining
    tools: it highlights cases that deviate from a defined reference process.
    """
    project_root = Path(__file__).resolve().parents[1]
    input_path = project_root / "data" / "processed" / "event_log_clean.csv"
    output_dir = project_root / "data" / "processed"
    database_path = project_root / "database.db"

    if not input_path.exists():
        raise FileNotFoundError(f"{input_path.name} is missing. Run 'python src/main.py' first.")

    event_log = pd.read_csv(input_path)
    event_log["timestamp"] = pd.to_datetime(event_log["timestamp"], errors="coerce")
    event_log = event_log.sort_values(["case_id", "timestamp"]).reset_index(drop=True)

    report_rows = []
    for case_id, case_events in event_log.groupby("case_id", sort=False):
        actual_activities = case_events["activity"].dropna().tolist()
        actual_activity_set = set(actual_activities)
        expected_activity_set = set(EXPECTED_SEQUENCE)
        missing_steps = ordered_steps(expected_activity_set - actual_activity_set)
        unexpected_steps = sorted(actual_activity_set - expected_activity_set)

        # Compare only known activities to find out whether their relative order
        # moves backwards compared with the defined reference process.
        known_activity_positions = [
            EXPECTED_SEQUENCE.index(activity)
            for activity in actual_activities
            if activity in expected_activity_set
        ]
        wrong_order_detected = known_activity_positions != sorted(known_activity_positions)
        is_conformant = actual_activities == EXPECTED_SEQUENCE

        report_rows.append(
            {
                "case_id": case_id,
                "region": case_events["region"].iloc[0] if "region" in case_events.columns else "Unknown",
                "actual_sequence": " → ".join(actual_activities),
                "is_conformant": is_conformant,
                "missing_steps": ", ".join(missing_steps),
                "unexpected_steps": ", ".join(unexpected_steps),
                "wrong_order_detected": wrong_order_detected,
            }
        )

    report = pd.DataFrame(report_rows)
    total_cases = len(report)
    conformant_cases = int(report["is_conformant"].sum())
    non_conformant_cases = total_cases - conformant_cases
    regional_deviations = (
        report.loc[~report["is_conformant"]]
        .groupby("region")
        .size()
        .sort_values(ascending=False)
    )
    top_regions_with_deviations = [
        {"region": region, "deviation_count": int(count)}
        for region, count in regional_deviations.items()
    ]

    summary = {
        "total_cases": total_cases,
        "conformant_cases": conformant_cases,
        "non_conformant_cases": non_conformant_cases,
        "conformance_rate_percent": round((conformant_cases / max(total_cases, 1)) * 100, 2),
        "top_regions_with_deviations": top_regions_with_deviations,
    }

    report.to_csv(output_dir / "conformance_report.csv", index=False)
    with (output_dir / "conformance_summary.json").open("w", encoding="utf-8") as summary_file:
        json.dump(summary, summary_file, indent=2)

    with sqlite3.connect(database_path) as connection:
        report.to_sql("conformance_report", connection, if_exists="replace", index=False)

    print("Process Conformance Summary")
    print(f"Total cases: {total_cases}")
    print(f"Conformant cases: {conformant_cases}")
    print(f"Non-conformant cases: {non_conformant_cases}")
    print(f"Conformance rate: {summary['conformance_rate_percent']}%")


if __name__ == "__main__":
    main()

"""Run data-quality checks on the cleaned event log."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pandas as pd


EXPECTED_ACTIVITIES = [
    "Order Created",
    "Order Approved",
    "Production Started",
    "Quality Check",
    "Shipping Started",
    "Delivered",
]


def add_report_row(
    report_rows: list[dict],
    check_name: str,
    issue_count: int,
    case_id: str = "",
    column: str = "",
    issue_detail: str = "",
) -> None:
    """Add one consistently structured row to the quality report."""
    report_rows.append(
        {
            "check_name": check_name,
            "case_id": case_id,
            "column": column,
            "issue_detail": issue_detail,
            "issue_count": issue_count,
        }
    )


def main() -> None:
    """Check data quality and store the results for ETL monitoring."""
    project_root = Path(__file__).resolve().parents[1]
    input_path = project_root / "data" / "processed" / "event_log_clean.csv"
    output_dir = project_root / "data" / "processed"
    database_path = project_root / "database.db"

    if not input_path.exists():
        raise FileNotFoundError(f"{input_path.name} is missing. Run 'python src/main.py' first.")

    # Quality checks are important in ETL jobs because incorrect source data can
    # lead to unreliable metrics, process insights, and business decisions.
    event_log = pd.read_csv(input_path)
    event_log = event_log.replace(r"^\s*$", pd.NA, regex=True)
    event_log["timestamp"] = pd.to_datetime(event_log["timestamp"], errors="coerce")
    report_rows: list[dict] = []

    # 1. Show the number of missing values for every column.
    missing_values = event_log.isna().sum()
    for column, missing_count in missing_values.items():
        add_report_row(
            report_rows,
            "Missing values",
            int(missing_count),
            column=column,
            issue_detail=f"{missing_count} missing value(s)",
        )

    # 2. Identify repeated business events using their case, activity, and time.
    duplicate_mask = event_log.duplicated(["case_id", "activity", "timestamp"], keep="first")
    duplicate_event_count = int(duplicate_mask.sum())
    for _, duplicate in event_log.loc[duplicate_mask].iterrows():
        add_report_row(
            report_rows,
            "Duplicate event",
            1,
            case_id=str(duplicate["case_id"]),
            issue_detail=f"Duplicate {duplicate['activity']} event at {duplicate['timestamp']}",
        )

    grouped_cases = event_log.groupby("case_id", dropna=False)

    # 3. Every case should include all six expected process activities.
    cases_with_missing_steps = 0
    for case_id, case_events in grouped_cases:
        missing_steps = sorted(set(EXPECTED_ACTIVITIES) - set(case_events["activity"].dropna()))
        if missing_steps:
            cases_with_missing_steps += 1
            add_report_row(
                report_rows,
                "Missing process steps",
                len(missing_steps),
                case_id=str(case_id),
                issue_detail=f"Missing: {', '.join(missing_steps)}",
            )

    # 4. Event timestamps must increase in the file's order for each case.
    cases_with_non_chronological_timestamps = 0
    for case_id, case_events in grouped_cases:
        if (case_events["timestamp"].diff().dt.total_seconds() < 0).any():
            cases_with_non_chronological_timestamps += 1
            add_report_row(
                report_rows,
                "Non-chronological timestamps",
                1,
                case_id=str(case_id),
                issue_detail="At least one event occurs before its preceding event.",
            )

    # 5. A complete order case should contain exactly six process events.
    case_event_counts = grouped_cases.size()
    wrong_event_count_cases = case_event_counts[case_event_counts.ne(len(EXPECTED_ACTIVITIES))]
    for case_id, event_count in wrong_event_count_cases.items():
        add_report_row(
            report_rows,
            "Wrong event count",
            1,
            case_id=str(case_id),
            issue_detail=f"Expected 6 events, found {event_count}.",
        )

    # 6. Activities outside the defined process make process analysis unreliable.
    invalid_activity_mask = ~event_log["activity"].isin(EXPECTED_ACTIVITIES)
    invalid_activity_count = int(invalid_activity_mask.sum())
    for _, invalid_event in event_log.loc[invalid_activity_mask].iterrows():
        add_report_row(
            report_rows,
            "Invalid activity",
            1,
            case_id=str(invalid_event["case_id"]),
            column="activity",
            issue_detail=f"Unexpected activity: {invalid_event['activity']}",
        )

    total_rows = len(event_log)
    total_cases = int(event_log["case_id"].nunique())
    issue_count = (
        duplicate_event_count
        + cases_with_missing_steps
        + len(wrong_event_count_cases)
        + cases_with_non_chronological_timestamps
        + invalid_activity_count
    )
    # The score is a simple, transparent indicator: more issues lower it, with
    # 100 representing no detected issues.
    data_quality_score = round(max(0, 100 - (issue_count / max(total_rows, 1) * 100)), 2)

    report = pd.DataFrame(
        report_rows,
        columns=["check_name", "case_id", "column", "issue_detail", "issue_count"],
    )
    report_path = output_dir / "data_quality_report.csv"
    summary_path = output_dir / "data_quality_summary.json"
    report.to_csv(report_path, index=False)

    summary = {
        "total_rows": int(total_rows),
        "total_cases": total_cases,
        "duplicate_event_count": duplicate_event_count,
        "cases_with_missing_steps": cases_with_missing_steps,
        "cases_with_wrong_event_count": int(len(wrong_event_count_cases)),
        "cases_with_non_chronological_timestamps": cases_with_non_chronological_timestamps,
        "invalid_activity_count": invalid_activity_count,
        "data_quality_score": data_quality_score,
    }
    with summary_path.open("w", encoding="utf-8") as summary_file:
        json.dump(summary, summary_file, indent=2)

    with sqlite3.connect(database_path) as connection:
        report.to_sql("data_quality_report", connection, if_exists="replace", index=False)

    print("Data Quality Summary")
    print(f"Total rows: {summary['total_rows']}")
    print(f"Total cases: {summary['total_cases']}")
    print(f"Duplicate events: {summary['duplicate_event_count']}")
    print(f"Cases with missing steps: {summary['cases_with_missing_steps']}")
    print(f"Cases with wrong event count: {summary['cases_with_wrong_event_count']}")
    print(f"Cases with non-chronological timestamps: {summary['cases_with_non_chronological_timestamps']}")
    print(f"Invalid activities: {summary['invalid_activity_count']}")
    print(f"Data quality score: {summary['data_quality_score']}/100")


if __name__ == "__main__":
    main()

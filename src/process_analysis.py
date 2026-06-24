"""Run a simplified Celonis-style process-mining analysis on the event log."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pandas as pd


# SLA limits (in hours) for the important handoffs in this order process.
SLA_THRESHOLDS = {
    "Order Created → Order Approved": 12,
    "Order Approved → Production Started": 24,
    "Production Started → Quality Check": 48,
    "Quality Check → Shipping Started": 24,
    "Shipping Started → Delivered": 72,
}


def main() -> None:
    """Analyse process flow, throughput, and SLA performance from SQLite data.

    This is a deliberately lightweight process-mining workflow inspired by the
    event-log analysis commonly performed in tools such as Celonis.
    """
    project_root = Path(__file__).resolve().parents[1]
    database_path = project_root / "database.db"
    output_dir = project_root / "data" / "processed"
    output_dir.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(database_path) as connection:
        event_log = pd.read_sql_query("SELECT * FROM event_log", connection)

    if event_log.empty:
        raise ValueError("The event_log table is empty. Run 'python src/main.py' first.")

    event_log["timestamp"] = pd.to_datetime(event_log["timestamp"], errors="raise")
    event_log = event_log.sort_values(["case_id", "timestamp"]).reset_index(drop=True)

    # Shift each case by one row to expose the next activity and its timestamp.
    transitions = event_log.copy()
    transitions["next_activity"] = transitions.groupby("case_id")["activity"].shift(-1)
    transitions["next_timestamp"] = transitions.groupby("case_id")["timestamp"].shift(-1)
    transitions = transitions.dropna(subset=["next_activity", "next_timestamp"]).copy()
    transitions["transition"] = transitions["activity"] + " → " + transitions["next_activity"]
    transitions["duration_hours"] = (
        (transitions["next_timestamp"] - transitions["timestamp"]).dt.total_seconds() / 3600
    ).round(2)
    transitions["sla_threshold_hours"] = transitions["transition"].map(SLA_THRESHOLDS)
    transitions["is_sla_violation"] = transitions["duration_hours"] > transitions["sla_threshold_hours"]

    # Throughput is the elapsed time from a case's first event to its last event.
    case_throughput = (
        event_log.groupby("case_id", as_index=False)
        .agg(start_timestamp=("timestamp", "min"), end_timestamp=("timestamp", "max"))
    )
    case_throughput["throughput_hours"] = (
        (case_throughput["end_timestamp"] - case_throughput["start_timestamp"]).dt.total_seconds() / 3600
    ).round(2)

    bottlenecks = (
        transitions.groupby("transition", as_index=False)
        .agg(average_duration_hours=("duration_hours", "mean"), transition_count=("transition", "size"))
        .sort_values("average_duration_hours", ascending=False)
        .reset_index(drop=True)
    )
    bottlenecks["average_duration_hours"] = bottlenecks["average_duration_hours"].round(2)
    sla_violations = transitions[transitions["is_sla_violation"]].copy()

    transitions.to_csv(output_dir / "transition_durations.csv", index=False)
    case_throughput.to_csv(output_dir / "case_throughput.csv", index=False)
    bottlenecks.to_csv(output_dir / "bottlenecks.csv", index=False)
    sla_violations.to_csv(output_dir / "sla_violations.csv", index=False)

    top_bottleneck = bottlenecks.iloc[0]
    summary = {
        "total_cases": int(event_log["case_id"].nunique()),
        "total_events": int(len(event_log)),
        "average_throughput_hours": round(float(case_throughput["throughput_hours"].mean()), 2),
        "max_throughput_hours": round(float(case_throughput["throughput_hours"].max()), 2),
        "total_sla_violations": int(sla_violations.shape[0]),
        "top_bottleneck_transition": top_bottleneck["transition"],
        "top_bottleneck_avg_hours": float(top_bottleneck["average_duration_hours"]),
    }
    with (output_dir / "process_summary.json").open("w", encoding="utf-8") as summary_file:
        json.dump(summary, summary_file, indent=2)

    # Persist analysis outputs so they can be queried alongside the original log.
    with sqlite3.connect(database_path) as connection:
        transitions.to_sql("transition_durations", connection, if_exists="replace", index=False)
        case_throughput.to_sql("case_throughput", connection, if_exists="replace", index=False)
        bottlenecks.to_sql("bottlenecks", connection, if_exists="replace", index=False)
        sla_violations.to_sql("sla_violations", connection, if_exists="replace", index=False)

    print("Top 5 bottlenecks:")
    # Use an ASCII arrow only for terminal output so this also runs in legacy
    # Windows console encodings that cannot render the Unicode arrow character.
    display_bottlenecks = bottlenecks.head(5).copy()
    display_bottlenecks["transition"] = display_bottlenecks["transition"].str.replace(" → ", " -> ", regex=False)
    print(display_bottlenecks.to_string(index=False))


if __name__ == "__main__":
    main()

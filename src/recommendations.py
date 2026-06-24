"""Generate simple business recommendations from process-analysis outputs."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pandas as pd


def add_recommendation(
    recommendations: list[dict], priority: str, category: str, finding: str, recommendation: str
) -> None:
    """Add one readable, rule-based recommendation."""
    recommendations.append(
        {
            "priority": priority,
            "category": category,
            "finding": finding,
            "recommendation": recommendation,
        }
    )


def main() -> None:
    """Create recommendations from bottlenecks, SLA results, and optional checks."""
    project_root = Path(__file__).resolve().parents[1]
    processed_dir = project_root / "data" / "processed"
    database_path = project_root / "database.db"
    bottlenecks_path = processed_dir / "bottlenecks.csv"
    violations_path = processed_dir / "sla_violations.csv"

    if not bottlenecks_path.exists() or not violations_path.exists():
        raise FileNotFoundError("Analysis files are missing. Run 'python src/process_analysis.py' first.")

    bottlenecks = pd.read_csv(bottlenecks_path)
    sla_violations = pd.read_csv(violations_path)
    recommendations: list[dict] = []

    # Long average handoffs point to capacity constraints or unclear ownership.
    for _, bottleneck in bottlenecks[bottlenecks["average_duration_hours"] >= 24].iterrows():
        add_recommendation(
            recommendations,
            "High",
            "Bottleneck",
            f"{bottleneck['transition']} takes {bottleneck['average_duration_hours']:.2f} hours on average.",
            "Review the handover between teams and check whether capacity planning can reduce waiting time.",
        )

    # A high share of SLA violations merits immediate attention for that step.
    if not sla_violations.empty:
        violation_counts = sla_violations.groupby("transition").size().rename("violation_count")
        transition_counts = bottlenecks.set_index("transition")["transition_count"]
        violation_rates = (violation_counts / transition_counts).fillna(0)
        for transition, violation_rate in violation_rates[violation_rates >= 0.10].items():
            add_recommendation(
                recommendations,
                "High",
                "SLA",
                f"{transition} exceeds its SLA in {violation_rate * 100:.1f}% of observed cases.",
                "Prioritize this process step and investigate the main causes of delayed cases.",
            )

    # Conformance data is optional because it is produced by a separate analysis step.
    conformance_path = processed_dir / "conformance_report.csv"
    if conformance_path.exists():
        conformance_report = pd.read_csv(conformance_path)
        deviations = conformance_report[~conformance_report["is_conformant"].astype(bool)]
        for region, count in deviations.groupby("region").size().sort_values(ascending=False).items():
            add_recommendation(
                recommendations,
                "Medium",
                "Conformance",
                f"{region} has {count} non-conformant case(s).",
                f"Standardize the order process in {region} and review local deviations from the expected workflow.",
            )

    # Data-quality data is also optional and is only actionable below the agreed threshold.
    quality_summary_path = processed_dir / "data_quality_summary.json"
    if quality_summary_path.exists():
        with quality_summary_path.open(encoding="utf-8") as summary_file:
            quality_summary = json.load(summary_file)
        quality_score = quality_summary.get("data_quality_score", 100)
        if quality_score < 95:
            add_recommendation(
                recommendations,
                "Medium",
                "Data Quality",
                f"The data-quality score is {quality_score}/100.",
                "Improve input-data validation to prevent incomplete, duplicate, or invalid process events.",
            )

    if not recommendations:
        add_recommendation(
            recommendations,
            "Low",
            "Process Health",
            "No rule-based critical issues were detected in the available analysis outputs.",
            "Continue monitoring process duration, SLA performance, conformance, and data quality regularly.",
        )

    recommendation_df = pd.DataFrame(recommendations)
    recommendation_df.to_csv(processed_dir / "recommendations.csv", index=False)
    with (processed_dir / "recommendations.json").open("w", encoding="utf-8") as recommendations_file:
        json.dump(recommendations, recommendations_file, indent=2)

    with sqlite3.connect(database_path) as connection:
        recommendation_df.to_sql("recommendations", connection, if_exists="replace", index=False)

    print(f"Generated {len(recommendation_df)} recommendation(s).")
    display_recommendations = recommendation_df[["priority", "category", "finding"]].copy()
    display_recommendations["finding"] = display_recommendations["finding"].str.replace(" → ", " -> ", regex=False)
    print(display_recommendations.to_string(index=False))


if __name__ == "__main__":
    main()

"""Generate simple business recommendations from process-analysis outputs."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sqlite3

import pandas as pd

from logging_config import configure_logging


logger = logging.getLogger(__name__)


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


def iqr_outlier_threshold(values: pd.Series) -> float:
    """Return the IQR upper fence for a series, used consistently across this
    project (transform.py's amount outliers, data_quality.py's case-length
    outliers) as the one way "unusually high" is defined here.
    """
    first_quartile = values.quantile(0.25)
    third_quartile = values.quantile(0.75)
    interquartile_range = third_quartile - first_quartile
    return third_quartile + 1.5 * interquartile_range


def main() -> None:
    """Create recommendations from bottlenecks, SLA results, and optional checks."""
    project_root = Path(__file__).resolve().parents[1]
    processed_dir = project_root / "data" / "processed"
    database_path = project_root / "database.db"
    bottlenecks_path = processed_dir / "bottlenecks.csv"
    violations_path = processed_dir / "sla_violations.csv"

    if not bottlenecks_path.exists() or not violations_path.exists():
        message = "Analysis files are missing. Run 'python src/process_analysis.py' first."
        logger.error(message)
        raise FileNotFoundError(message)

    bottlenecks = pd.read_csv(bottlenecks_path)
    sla_violations = pd.read_csv(violations_path)
    recommendations: list[dict] = []

    # Only transitions with enough occurrences to trust their statistics are
    # considered here -- process_analysis.py already flags the rest via
    # is_low_sample_transition, so this reuses that flag instead of
    # re-deriving it.
    reliable_bottlenecks = bottlenecks[~bottlenecks["is_low_sample_transition"]].copy()

    # Long average handoffs point to capacity constraints or unclear
    # ownership. BPI2012 durations naturally range from hours to weeks (real
    # human/queue time, not a synthetic SLA-tuned process), so a fixed hour
    # cutoff has no meaning here -- e.g. 24h would flag almost every step.
    # Instead, a transition is a "Bottleneck" recommendation only if its
    # average duration is a statistical outlier *relative to the process's
    # other reliable transitions* (same IQR technique used everywhere else
    # in this project), so the threshold self-calibrates to whatever this
    # process's normal pace actually is.
    if not reliable_bottlenecks.empty:
        duration_fence = iqr_outlier_threshold(reliable_bottlenecks["average_duration_hours"])
        outlier_bottlenecks = reliable_bottlenecks[reliable_bottlenecks["average_duration_hours"] > duration_fence]
        for _, bottleneck in outlier_bottlenecks.sort_values("average_duration_hours", ascending=False).iterrows():
            add_recommendation(
                recommendations,
                "High",
                "Bottleneck",
                f"{bottleneck['transition']} takes {bottleneck['average_duration_hours']:.2f} hours on average, "
                f"well above the process's typical pace (~{duration_fence:.2f}h).",
                "Review the handover between teams and check whether capacity planning can reduce waiting time.",
            )

    # NOTE on why this is no longer a violation-rate check: sla_threshold_hours
    # (process_analysis.py) is each transition's own 90th percentile, so by
    # construction roughly 10% of any transition's own occurrences exceed it
    # -- a ">=10% violation rate" filter is therefore close to a tautology,
    # not a signal (verified on this dataset: violation rates cluster in
    # 0%-12.1% for every transition, regardless of how well-behaved it is).
    # What *does* vary meaningfully is how far past its own threshold a
    # violation lands when it happens, so that -- the excess magnitude -- is
    # what is flagged here instead.
    if not sla_violations.empty:
        sla_violations = sla_violations.copy()
        sla_violations["excess_hours"] = sla_violations["duration_hours"] - sla_violations["sla_threshold_hours"]
        reliable_transitions = set(reliable_bottlenecks["transition"])
        reliable_violations = sla_violations[sla_violations["transition"].isin(reliable_transitions)]

        excess_by_transition = reliable_violations.groupby("transition")["excess_hours"].agg(
            mean_excess_hours="mean", violation_count="size"
        )
        if not excess_by_transition.empty:
            excess_fence = iqr_outlier_threshold(excess_by_transition["mean_excess_hours"])
            worst_transitions = excess_by_transition[excess_by_transition["mean_excess_hours"] > excess_fence]
            for transition, row in worst_transitions.sort_values("mean_excess_hours", ascending=False).iterrows():
                add_recommendation(
                    recommendations,
                    "High",
                    "SLA",
                    f"{transition} overshoots its own historical p90 duration by {row['mean_excess_hours']:.2f} "
                    f"hours on average across {int(row['violation_count'])} occurrence(s).",
                    "Investigate why this specific step occasionally runs far longer than its own normal pace, "
                    "rather than just how often it happens.",
                )

    # Conformance data is optional because it is produced by a separate analysis step.
    conformance_path = processed_dir / "conformance_report.csv"
    if conformance_path.exists():
        conformance_report = pd.read_csv(conformance_path)
        deviations = conformance_report[~conformance_report["is_conformant"].astype(bool)]
        if deviations.empty:
            # A 100% conformance rate is a real, checked result here (see
            # conformance_check.py), not an unrun check -- report it
            # explicitly so "Conformance" still appears as a category instead
            # of silently contributing nothing, which would look identical to
            # the check never having run.
            add_recommendation(
                recommendations,
                "Low",
                "Conformance",
                f"All {len(conformance_report)} case(s) conform to the checked precedence rules.",
                "No ordering violations detected; continue monitoring as new data arrives.",
            )
        else:
            # amount_category replaces the old region-based breakdown --
            # BPI2012 has no regional dimension, but grouping by requested
            # amount answers a comparable "where should we look first" question.
            for amount_category, count in (
                deviations.groupby("amount_category").size().sort_values(ascending=False).items()
            ):
                add_recommendation(
                    recommendations,
                    "Medium",
                    "Conformance",
                    f"{amount_category} requested-amount cases have {count} non-conformant case(s).",
                    f"Review why {amount_category} cases break the expected precedence rules "
                    "and whether that segment needs a distinct process path.",
                )

    # Data-quality data is also optional and is only actionable below the agreed threshold.
    quality_summary_path = processed_dir / "data_quality_summary.json"
    if quality_summary_path.exists():
        with quality_summary_path.open(encoding="utf-8") as summary_file:
            quality_summary = json.load(summary_file)
        quality_score = quality_summary.get("data_quality_score", 100)
        # data_quality.py normalizes its score against total_cases (not
        # total_rows), so <95 now means "more than ~5% of cases have a
        # detected issue" -- a meaningful, reachable bar again (previously,
        # with a row-based denominator, even every case having an issue only
        # brought the score to ~95, so this threshold could never fire).
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

    logger.info("Generated %d recommendation(s).", len(recommendation_df))

    # Kept as plain print(), same reasoning as the bottleneck table in
    # process_analysis.py: this is the script's actual report output for a
    # human reading the terminal, not an operational log event.
    display_recommendations = recommendation_df[["priority", "category", "finding"]].copy()
    display_recommendations["finding"] = display_recommendations["finding"].str.replace(" → ", " -> ", regex=False)
    print(display_recommendations.to_string(index=False))


if __name__ == "__main__":
    configure_logging()
    main()

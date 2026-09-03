"""Run a simplified Celonis-style process-mining analysis on the event log."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd

from logging_config import configure_logging


logger = logging.getLogger(__name__)


# BPI2012 has 24 activities and no fixed step sequence (unlike the earlier
# synthetic 6-step SAP log), so there is no externally defined reference
# process or contractual SLA to hardcode. Both the "expected process" and the
# "abnormal duration" threshold are therefore discovered from the log itself:
# a transition's own historical duration distribution is used to judge
# whether a given occurrence of it was unusually slow.

# A percentile (rather than a fixed hour count) scales automatically to each
# transition's own duration distribution -- e.g. a rework loop that normally
# takes days is judged against its own days-long baseline, not a value tuned
# for a different transition. 0.90 mirrors how tools like Celonis commonly
# flag the slowest ~10% of occurrences of a given step as bottleneck cases.
SLA_PERCENTILE = 0.90

# A percentile computed from a handful of observations is unstable (e.g. with
# 2 occurrences, the 90th percentile is just whichever one is larger). 30 is
# the common statistical rule-of-thumb for "large enough sample to trust a
# summary statistic". Transitions below this are marked instead of silently
# assigned a threshold that looks precise but isn't.
MIN_TRANSITION_SAMPLE_SIZE = 30

# Number of most-frequent case variants (exact COMPLETE-activity sequences)
# to report as the discovered "happy path" candidates.
TOP_VARIANTS_TO_REPORT = 15


def compute_transition_thresholds(transitions: pd.DataFrame) -> pd.DataFrame:
    """Derive a per-transition duration threshold from the log itself.

    Returns one row per distinct transition with its occurrence count and the
    SLA_PERCENTILE duration, so each transition is judged against how it
    normally behaves rather than one fixed number applied to every step.
    """
    stats = transitions.groupby("transition")["duration_hours"].agg(
        transition_count="size",
        sla_threshold_hours=lambda durations: durations.quantile(SLA_PERCENTILE),
    )
    stats["has_sufficient_sla_sample"] = stats["transition_count"] >= MIN_TRANSITION_SAMPLE_SIZE
    # Below the sample-size floor, drop the threshold rather than keep a
    # number computed from too few points: NaN makes any comparison against
    # it False, so these transitions are automatically excluded from SLA
    # violations instead of needing a separate filter everywhere downstream.
    stats.loc[~stats["has_sufficient_sla_sample"], "sla_threshold_hours"] = np.nan
    return stats.reset_index()


def discover_process_variants(complete_events: pd.DataFrame) -> pd.DataFrame:
    """Discover case variants (exact activity sequences) and rank by frequency.

    This is the concrete "happy path" discovery step: rather than assuming a
    reference process, every case's actual COMPLETE-activity sequence is
    grouped and counted, and the most frequent ones are reported with their
    coverage of the case population.
    """
    case_variants = complete_events.groupby("case_id")["activity"].apply(lambda activities: " -> ".join(activities))
    total_cases = case_variants.shape[0]

    variant_counts = case_variants.value_counts().reset_index()
    variant_counts.columns = ["variant", "case_count"]
    variant_counts["coverage_percent"] = (variant_counts["case_count"] / total_cases * 100).round(2)
    variant_counts["cumulative_coverage_percent"] = variant_counts["coverage_percent"].cumsum().round(2)
    return variant_counts


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

    # SQLite stores timestamps as text, and pandas' string repr of a
    # Timestamp omits trailing zero microseconds -- so rows are not all in
    # the exact same sub-format. format="ISO8601" parses each independently
    # instead of assuming one fixed pattern.
    event_log["timestamp"] = pd.to_datetime(event_log["timestamp"], errors="raise", utc=True, format="ISO8601")
    # SQLite has no boolean type: bool columns come back as 0/1 integers.
    event_log["is_complete_event"] = event_log["is_complete_event"].astype(bool)
    event_log = event_log.sort_values(["case_id", "timestamp"]).reset_index(drop=True)

    # Throughput reflects how long a case actually existed in the system, so
    # it is measured across every lifecycle state (SCHEDULE/START/COMPLETE),
    # not just COMPLETE events.
    case_throughput = event_log.groupby("case_id", as_index=False).agg(
        start_timestamp=("timestamp", "min"), end_timestamp=("timestamp", "max")
    )
    case_throughput["throughput_hours"] = (
        (case_throughput["end_timestamp"] - case_throughput["start_timestamp"]).dt.total_seconds() / 3600
    ).round(2)

    # Control-flow analysis (transitions, bottlenecks, variants) uses only
    # COMPLETE events. Keeping SCHEDULE/START here would turn a single
    # activity's own lifecycle steps (e.g. W_X SCHEDULE -> W_X START) into
    # fake "transitions" interleaved with the real next-activity relationship,
    # corrupting both the bottleneck table and the variant sequences below.
    complete_events = event_log[event_log["is_complete_event"]].sort_values(["case_id", "timestamp"]).reset_index(
        drop=True
    )

    transitions = complete_events.copy()
    transitions["next_activity"] = transitions.groupby("case_id")["activity"].shift(-1)
    transitions["next_timestamp"] = transitions.groupby("case_id")["timestamp"].shift(-1)
    transitions = transitions.dropna(subset=["next_activity", "next_timestamp"]).copy()
    transitions["transition"] = transitions["activity"] + " → " + transitions["next_activity"]
    transitions["duration_hours"] = (
        (transitions["next_timestamp"] - transitions["timestamp"]).dt.total_seconds() / 3600
    ).round(2)

    transition_thresholds = compute_transition_thresholds(transitions)
    transitions = transitions.merge(
        transition_thresholds[["transition", "sla_threshold_hours", "has_sufficient_sla_sample"]],
        on="transition",
        how="left",
    )
    transitions["is_sla_violation"] = transitions["duration_hours"] > transitions["sla_threshold_hours"]

    bottlenecks = (
        transitions.groupby("transition", as_index=False)
        .agg(average_duration_hours=("duration_hours", "mean"), transition_count=("transition", "size"))
        .sort_values("average_duration_hours", ascending=False)
        .reset_index(drop=True)
    )
    bottlenecks["average_duration_hours"] = bottlenecks["average_duration_hours"].round(2)
    # Visible, not filtered out: a transition seen only a handful of times can
    # land at the top purely by chance (one slow occurrence dominates a small
    # mean). The flag lets readers of bottlenecks.csv see that risk themselves
    # instead of the row being silently dropped or, worse, silently trusted.
    bottlenecks["is_low_sample_transition"] = bottlenecks["transition_count"] < MIN_TRANSITION_SAMPLE_SIZE

    sla_violations = transitions[transitions["is_sla_violation"]].copy()

    process_variants = discover_process_variants(complete_events)
    top_variants = process_variants.head(TOP_VARIANTS_TO_REPORT)

    transitions.to_csv(output_dir / "transition_durations.csv", index=False)
    case_throughput.to_csv(output_dir / "case_throughput.csv", index=False)
    bottlenecks.to_csv(output_dir / "bottlenecks.csv", index=False)
    sla_violations.to_csv(output_dir / "sla_violations.csv", index=False)
    top_variants.to_csv(output_dir / "process_variants.csv", index=False)

    # The headline "top bottleneck" excludes low-sample transitions for the
    # same reason they are flagged above: reporting a two-occurrence fluke as
    # THE bottleneck in the summary/dashboard KPI would be more misleading
    # than a flagged row buried in a CSV, since it is the one number most
    # likely to be read on its own.
    reliable_bottlenecks = bottlenecks[~bottlenecks["is_low_sample_transition"]]
    top_bottleneck = (reliable_bottlenecks if not reliable_bottlenecks.empty else bottlenecks).iloc[0]

    summary = {
        "total_cases": int(event_log["case_id"].nunique()),
        "total_events": int(len(event_log)),
        "complete_events": int(len(complete_events)),
        "average_throughput_hours": round(float(case_throughput["throughput_hours"].mean()), 2),
        "max_throughput_hours": round(float(case_throughput["throughput_hours"].max()), 2),
        "total_sla_violations": int(sla_violations.shape[0]),
        "transitions_with_insufficient_sla_sample": int((~transition_thresholds["has_sufficient_sla_sample"]).sum()),
        "top_bottleneck_transition": top_bottleneck["transition"],
        "top_bottleneck_avg_hours": float(top_bottleneck["average_duration_hours"]),
        "distinct_process_variants": int(len(process_variants)),
        "top_variant_coverage_percent": float(process_variants.iloc[0]["coverage_percent"]),
        "cases_covered_by_top_variants_report": int(top_variants["case_count"].sum()),
    }
    with (output_dir / "process_summary.json").open("w", encoding="utf-8") as summary_file:
        json.dump(summary, summary_file, indent=2)

    if summary["transitions_with_insufficient_sla_sample"] > 0:
        # WARNING, not INFO: these transitions' is_sla_violation values are
        # not meaningful (see compute_transition_thresholds) -- a reader of
        # sla_violations.csv or the dashboard should know part of the result
        # is deliberately incomplete, not just get a quiet fact in the log.
        logger.warning(
            "%d transition(s) have too few occurrences (<%d) for a reliable SLA threshold; "
            "they are excluded from SLA violation counts.",
            summary["transitions_with_insufficient_sla_sample"],
            MIN_TRANSITION_SAMPLE_SIZE,
        )

    # Persist analysis outputs so they can be queried alongside the original log.
    with sqlite3.connect(database_path) as connection:
        transitions.to_sql("transition_durations", connection, if_exists="replace", index=False)
        case_throughput.to_sql("case_throughput", connection, if_exists="replace", index=False)
        bottlenecks.to_sql("bottlenecks", connection, if_exists="replace", index=False)
        sla_violations.to_sql("sla_violations", connection, if_exists="replace", index=False)
        process_variants.to_sql("process_variants", connection, if_exists="replace", index=False)

    logger.info(
        "Process analysis complete: %d cases, %d events, %d SLA violation(s), %d distinct variants.",
        summary["total_cases"],
        summary["total_events"],
        summary["total_sla_violations"],
        summary["distinct_process_variants"],
    )

    # This table is the script's actual report output for a human reading the
    # terminal, not an operational log event -- kept as plain print() rather
    # than folded into a logger call, the same way you wouldn't route a
    # DataFrame dump through a logger in most codebases. The logger.info
    # calls above and below still leave a structured, one-line trace of the
    # same run in logs/pipeline.log for later/automated inspection.
    print(f"\nTop 5 bottlenecks (reliable, transition_count >= {MIN_TRANSITION_SAMPLE_SIZE}):")
    # Use an ASCII arrow only for terminal output so this also runs in legacy
    # Windows console encodings that cannot render the Unicode arrow character.
    display_bottlenecks = reliable_bottlenecks.head(5).copy()
    display_bottlenecks["transition"] = display_bottlenecks["transition"].str.replace(" → ", " -> ", regex=False)
    print(display_bottlenecks.to_string(index=False))

    logger.info(
        "Discovered %d distinct process variants; top variant covers %.2f%% of cases, "
        "top %d variants cover %.2f%% combined.",
        summary["distinct_process_variants"],
        summary["top_variant_coverage_percent"],
        TOP_VARIANTS_TO_REPORT,
        round(top_variants["coverage_percent"].sum(), 2),
    )


if __name__ == "__main__":
    configure_logging()
    main()

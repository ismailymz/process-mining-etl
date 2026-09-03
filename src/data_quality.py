"""Run data-quality checks on the cleaned event log."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sqlite3

import pandas as pd

from logging_config import configure_logging


logger = logging.getLogger(__name__)


# The 24 activity names actually observed in the BPI2012 reference log. This
# is a controlled vocabulary, deliberately hardcoded rather than derived from
# the file being checked: computing "valid activities" from the same batch
# you are validating is circular (whatever is present always passes). If the
# process changes and a genuinely new activity is introduced, extend this
# list deliberately -- don't let the check silently redefine "valid" around it.
KNOWN_ACTIVITIES = [
    "A_ACCEPTED", "A_ACTIVATED", "A_APPROVED", "A_CANCELLED", "A_DECLINED",
    "A_FINALIZED", "A_PARTLYSUBMITTED", "A_PREACCEPTED", "A_REGISTERED", "A_SUBMITTED",
    "O_ACCEPTED", "O_CANCELLED", "O_CREATED", "O_DECLINED", "O_SELECTED",
    "O_SENT", "O_SENT_BACK",
    "W_Afhandelen leads", "W_Beoordelen fraude", "W_Completeren aanvraag",
    "W_Nabellen incomplete dossiers", "W_Nabellen offertes", "W_Valideren aanvraag",
    "W_Wijzigen contractgegevens",
]

# A_SUBMITTED is the one activity that genuinely cannot come after anything
# else -- no case can exist before its application is submitted. Verified
# against the reference log: 0 violations out of 13,087 cases. Unlike a fixed
# 6-step sequence, this survives the process's real variability (24
# activities, rework loops, multiple outcomes) because it makes no claim
# about what happens *after* the first event.
REQUIRED_STARTING_ACTIVITY = "A_SUBMITTED"


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


def find_duplicate_events(event_log: pd.DataFrame) -> pd.DataFrame:
    """Return the rows that repeat an earlier case/activity/lifecycle/timestamp.

    lifecycle_transition is part of the key because a real activity
    legitimately produces up to three rows (SCHEDULE/START/COMPLETE) that can
    share a case, activity, and even a timestamp -- without it, those would
    be misreported as duplicates.
    """
    duplicate_mask = event_log.duplicated(["case_id", "activity", "lifecycle_transition", "timestamp"], keep="first")
    return event_log.loc[duplicate_mask]


def find_invalid_starting_cases(
    event_log: pd.DataFrame, required_starting_activity: str = REQUIRED_STARTING_ACTIVITY
) -> pd.Series:
    """Return, per case not starting with required_starting_activity, its actual first activity.

    Every case must start with A_SUBMITTED -- a real process invariant, not a
    majority pattern. Sorted by timestamp specifically for this check (not
    relying on file order) so that an out-of-order export doesn't hide a
    genuine starting-activity problem, or vice versa.
    """
    first_activity_by_case = event_log.sort_values(["case_id", "timestamp"]).groupby("case_id", dropna=False)[
        "activity"
    ].first()
    return first_activity_by_case[first_activity_by_case != required_starting_activity]


def find_unusual_length_cases(event_log: pd.DataFrame) -> tuple[pd.Series, float, float]:
    """Return (cases with a statistically unusual COMPLETE-event count, lower_fence, upper_fence).

    BPI2012 cases have no fixed length (rework loops repeat activities a
    variable number of times, and different outcomes take different paths),
    so there is no single "correct" event count to check against. Instead,
    an IQR-based outlier check (the same technique used for amount_requested
    in transform.py) flags cases whose COMPLETE-event count is statistically
    unusual relative to the rest of the batch -- reported as "unusual", not
    "wrong", since the true expected length isn't knowable without a process
    owner's input.
    """
    complete_case_lengths = event_log.loc[event_log["is_complete_event"]].groupby("case_id", dropna=False).size()
    first_quartile = complete_case_lengths.quantile(0.25)
    third_quartile = complete_case_lengths.quantile(0.75)
    interquartile_range = third_quartile - first_quartile
    lower_fence = first_quartile - 1.5 * interquartile_range
    upper_fence = third_quartile + 1.5 * interquartile_range
    unusual_length_cases = complete_case_lengths[
        (complete_case_lengths < lower_fence) | (complete_case_lengths > upper_fence)
    ]
    return unusual_length_cases, lower_fence, upper_fence


def main() -> None:
    """Check data quality and store the results for ETL monitoring."""
    project_root = Path(__file__).resolve().parents[1]
    input_path = project_root / "data" / "processed" / "event_log_clean.csv"
    output_dir = project_root / "data" / "processed"
    database_path = project_root / "database.db"

    if not input_path.exists():
        message = f"{input_path.name} is missing. Run 'python src/main.py' first."
        logger.error(message)
        raise FileNotFoundError(message)

    # Quality checks are important in ETL jobs because incorrect source data can
    # lead to unreliable metrics, process insights, and business decisions.
    event_log = pd.read_csv(input_path, low_memory=False)
    event_log = event_log.replace(r"^\s*$", pd.NA, regex=True)
    # format="ISO8601" is required here: pandas' string repr of a tz-aware
    # timestamp drops trailing zero microseconds, so rows are not all in the
    # exact same sub-format -- a fixed-format parse would silently coerce a
    # fraction of valid timestamps to NaT instead of raising on them.
    event_log["timestamp"] = pd.to_datetime(event_log["timestamp"], errors="coerce", utc=True, format="ISO8601")
    event_log["is_complete_event"] = event_log["is_complete_event"].astype(bool)
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

    # 2. Identify repeated business events using their case, activity,
    # lifecycle stage, and time.
    duplicate_events = find_duplicate_events(event_log)
    duplicate_event_count = len(duplicate_events)
    for _, duplicate in duplicate_events.iterrows():
        add_report_row(
            report_rows,
            "Duplicate event",
            1,
            case_id=str(duplicate["case_id"]),
            issue_detail=f"Duplicate {duplicate['activity']} ({duplicate['lifecycle_transition']}) event at {duplicate['timestamp']}",
        )

    grouped_cases = event_log.groupby("case_id", dropna=False)

    # 3. Every case must start with A_SUBMITTED.
    invalid_starting_cases = find_invalid_starting_cases(event_log)
    for case_id, actual_first_activity in invalid_starting_cases.items():
        add_report_row(
            report_rows,
            "Invalid starting activity",
            1,
            case_id=str(case_id),
            issue_detail=f"Case starts with '{actual_first_activity}', expected '{REQUIRED_STARTING_ACTIVITY}'.",
        )

    # 4. Statistically unusual COMPLETE-event count (IQR-based).
    unusual_length_cases, lower_fence, upper_fence = find_unusual_length_cases(event_log)
    for case_id, event_count in unusual_length_cases.items():
        add_report_row(
            report_rows,
            "Unusual case length",
            1,
            case_id=str(case_id),
            issue_detail=f"{event_count} COMPLETE events (expected roughly {lower_fence:.1f}-{upper_fence:.1f}).",
        )

    # 5. Event timestamps must increase in the file's order for each case.
    # Deliberately checked against the file's own row order (not re-sorted
    # first) -- the point of this check is to catch an export/extraction bug
    # that scrambled row order, which sorting away would hide.
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

    # 6. Activities outside the known vocabulary make process analysis
    # unreliable -- this check is still meaningful with 24 activities, it
    # just validates against the wider, explicitly maintained KNOWN_ACTIVITIES
    # list above instead of a fixed 6-step sequence.
    invalid_activity_mask = ~event_log["activity"].isin(KNOWN_ACTIVITIES)
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
        + len(invalid_starting_cases)
        + len(unusual_length_cases)
        + cases_with_non_chronological_timestamps
        + invalid_activity_count
    )
    # The score is a simple, transparent indicator: more issues lower it, with
    # 100 representing no detected issues. Normalized against total_cases, not
    # total_rows: every check above (duplicates and invalid activities
    # included) is reported and reasoned about per case, so total_rows
    # (262,200 events) would dwarf issue_count and make the score
    # insensitive -- even every case having an issue would only move it to
    # ~95. Against total_cases (13,087) the score actually reflects what
    # fraction of cases have a detected problem.
    data_quality_score = round(max(0, 100 - (issue_count / max(total_cases, 1) * 100)), 2)

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
        "cases_with_invalid_starting_activity": int(len(invalid_starting_cases)),
        "cases_with_unusual_length": int(len(unusual_length_cases)),
        "cases_with_non_chronological_timestamps": cases_with_non_chronological_timestamps,
        "invalid_activity_count": invalid_activity_count,
        "data_quality_score": data_quality_score,
    }
    with summary_path.open("w", encoding="utf-8") as summary_file:
        json.dump(summary, summary_file, indent=2)

    with sqlite3.connect(database_path) as connection:
        report.to_sql("data_quality_report", connection, if_exists="replace", index=False)

    logger.info(
        "Data quality check complete: %d rows, %d cases, %d duplicate event(s), "
        "%d invalid-start case(s), %d unusual-length case(s), %d non-chronological case(s), "
        "%d invalid activity event(s), score %.2f/100.",
        summary["total_rows"],
        summary["total_cases"],
        summary["duplicate_event_count"],
        summary["cases_with_invalid_starting_activity"],
        summary["cases_with_unusual_length"],
        summary["cases_with_non_chronological_timestamps"],
        summary["invalid_activity_count"],
        summary["data_quality_score"],
    )

    # WARNING, not just INFO: unusual case length is the one check in this
    # file with no fixed pass/fail rule (it's a statistical flag, not a known
    # invariant like the starting-activity check) -- worth calling out
    # separately so it doesn't blend into the routine summary line above.
    if summary["cases_with_unusual_length"] > 0:
        logger.warning(
            "%d case(s) have a statistically unusual COMPLETE-event count; see data_quality_report.csv.",
            summary["cases_with_unusual_length"],
        )

    # WARNING: this is the exact threshold recommendations.py gates its
    # "Data Quality" recommendation on -- if it fires, it should be visible
    # in the log at the moment it happens, not only inferred later from
    # recommendations.csv.
    if summary["data_quality_score"] < 95:
        logger.warning(
            "Data quality score %.2f is below the 95 threshold used by recommendations.py.",
            summary["data_quality_score"],
        )


if __name__ == "__main__":
    configure_logging()
    main()

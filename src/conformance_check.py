"""Run a simplified process-conformance check on the cleaned event log.

Conformance approach
---------------------
BPI2012 has no single reference sequence: 24 activities, rework loops, and
multiple business outcomes (declined / approved / cancelled) produce 4,336
distinct exact activity sequences across 13,087 cases (see
process_variants.csv). Comparing a case's trace to one fixed sequence -- or
even to its top-N most frequent variants -- would misclassify normal
variability as non-conformance: the single most common variant covers only
~26% of cases, and the top 15 combined cover ~51%. A variant-membership rule
would therefore flag roughly half of all cases as "wrong" simply for taking
a valid but less common path (e.g. more rework call-backs, or a different
outcome).

Instead, this checks a small set of **precedence constraints**, in the style
of Declare (a declarative process-modeling language from the process-mining
literature). Rather than one prescriptive model that enumerates every
allowed path, Declare expresses a process as independent rules of the form
"if B ever happens in this case, A must have happened before it" -- without
asserting anything about cases where B never happens at all. This tolerates
optional activities, repeated activities, and skipped branches (exactly the
variability this log has) while still catching genuine ordering violations,
such as a corrupted export where events land out of sequence.

Every constraint below was checked against the full reference log before
being hardcoded here: 0 violations across every case where the relevant
activities occur (up to 13,087 cases checked per constraint).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sqlite3

import pandas as pd

from data_quality import KNOWN_ACTIVITIES, REQUIRED_STARTING_ACTIVITY
from logging_config import configure_logging


logger = logging.getLogger(__name__)


# Declare "Precedence(predecessor, successor)": whenever `successor` occurs
# in a case, `predecessor` must occur earlier in that same case. Only
# evaluated for cases where both activities are present, so a case that
# never reaches `successor` (e.g. an application declined before an offer
# was ever created) is simply not subject to the rule -- it is not a
# violation by omission.
PRECEDENCE_CONSTRAINTS = [
    ("A_PARTLYSUBMITTED", "A_PREACCEPTED", "A_PARTLYSUBMITTED must precede A_PREACCEPTED"),
    ("A_PARTLYSUBMITTED", "A_DECLINED", "A_PARTLYSUBMITTED must precede A_DECLINED"),
    ("O_CREATED", "O_SENT", "O_CREATED must precede O_SENT"),
    ("A_ACCEPTED", "A_FINALIZED", "A_ACCEPTED must precede A_FINALIZED"),
    ("A_ACCEPTED", "A_APPROVED", "A_ACCEPTED must precede A_APPROVED"),
]


def find_violated_constraints(activities: list[str]) -> list[str]:
    """Return human-readable descriptions of every violated constraint.

    `activities` is a single case's COMPLETE-event activities in
    chronological order. Control-flow constraints are checked on COMPLETE
    events only, matching process_analysis.py: SCHEDULE/START rows describe
    lifecycle progress of one activity instance, not the case's control flow.
    """
    violations: list[str] = []

    # Declare "Init(A)": A must be the first event of every case.
    if activities and activities[0] != REQUIRED_STARTING_ACTIVITY:
        violations.append(f"Does not start with {REQUIRED_STARTING_ACTIVITY} (starts with {activities[0]})")

    for predecessor, successor, description in PRECEDENCE_CONSTRAINTS:
        if predecessor in activities and successor in activities:
            if activities.index(predecessor) > activities.index(successor):
                violations.append(description)

    return violations


def main() -> None:
    """Compare each case against a small set of process-wide precedence rules.

    This is a simplified process-conformance analysis inspired by
    Declare-style conformance checking: it flags cases that break a known
    ordering rule, rather than cases that merely take an unusual (but valid)
    path.
    """
    project_root = Path(__file__).resolve().parents[1]
    input_path = project_root / "data" / "processed" / "event_log_clean.csv"
    output_dir = project_root / "data" / "processed"
    database_path = project_root / "database.db"

    if not input_path.exists():
        message = f"{input_path.name} is missing. Run 'python src/main.py' first."
        logger.error(message)
        raise FileNotFoundError(message)

    event_log = pd.read_csv(input_path, low_memory=False)
    # format="ISO8601": see the matching comment in data_quality.py -- CSV
    # round-tripping produces inconsistent sub-second precision across rows.
    event_log["timestamp"] = pd.to_datetime(event_log["timestamp"], errors="coerce", utc=True, format="ISO8601")
    event_log["is_complete_event"] = event_log["is_complete_event"].astype(bool)
    complete_events = event_log[event_log["is_complete_event"]].sort_values(["case_id", "timestamp"]).reset_index(
        drop=True
    )

    report_rows = []
    for case_id, case_events in complete_events.groupby("case_id", sort=False):
        actual_activities = case_events["activity"].dropna().tolist()
        actual_activity_set = set(actual_activities)
        unexpected_steps = sorted(actual_activity_set - set(KNOWN_ACTIVITIES))
        violated_constraints = find_violated_constraints(actual_activities)
        is_conformant = not unexpected_steps and not violated_constraints

        report_rows.append(
            {
                "case_id": case_id,
                # amount_category replaces the old "region" breakdown -- BPI2012
                # has no regional dimension, but grouping deviations by
                # requested-amount size answers a comparable business question
                # (are larger/riskier applications more likely to deviate?).
                "amount_category": case_events["amount_category"].iloc[0]
                if "amount_category" in case_events.columns
                else "Unknown",
                "actual_sequence": " → ".join(actual_activities),
                "is_conformant": is_conformant,
                "unexpected_steps": ", ".join(unexpected_steps),
                "violated_constraints": "; ".join(violated_constraints),
            }
        )

    report = pd.DataFrame(report_rows)
    total_cases = len(report)
    conformant_cases = int(report["is_conformant"].sum())
    non_conformant_cases = total_cases - conformant_cases
    deviations_by_amount_category = (
        report.loc[~report["is_conformant"]]
        .groupby("amount_category")
        .size()
        .sort_values(ascending=False)
    )
    top_amount_categories_with_deviations = [
        {"amount_category": category, "deviation_count": int(count)}
        for category, count in deviations_by_amount_category.items()
    ]

    summary = {
        "total_cases": total_cases,
        "conformant_cases": conformant_cases,
        "non_conformant_cases": non_conformant_cases,
        "conformance_rate_percent": round((conformant_cases / max(total_cases, 1)) * 100, 2),
        "top_amount_categories_with_deviations": top_amount_categories_with_deviations,
    }

    report.to_csv(output_dir / "conformance_report.csv", index=False)
    with (output_dir / "conformance_summary.json").open("w", encoding="utf-8") as summary_file:
        json.dump(summary, summary_file, indent=2)

    with sqlite3.connect(database_path) as connection:
        report.to_sql("conformance_report", connection, if_exists="replace", index=False)

    logger.info(
        "Conformance check complete: %d/%d case(s) conformant (%.2f%%).",
        conformant_cases,
        total_cases,
        summary["conformance_rate_percent"],
    )

    # WARNING: a genuine precedence-rule violation is a stronger signal than
    # the "unusual length" flag in data_quality.py -- every constraint here
    # was verified to have 0 violations in the reference log (see module
    # docstring), so any non-conformant case found in a later run means
    # either corrupted input or a real process exception worth a human
    # actually looking at, not just a routine count.
    if non_conformant_cases > 0:
        logger.warning(
            "%d non-conformant case(s) found (%.2f%% of cases); see conformance_report.csv.",
            non_conformant_cases,
            round(100 - summary["conformance_rate_percent"], 2),
        )


if __name__ == "__main__":
    configure_logging()
    main()

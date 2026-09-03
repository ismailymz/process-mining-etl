"""Shared test fixtures for the ETL pipeline test suite."""

import pandas as pd


def make_event_log(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal raw event-log DataFrame for transform_event_log tests.

    Each row only needs to specify the columns it cares about -- every other
    required column gets a sensible default, so a test reads as "what's
    different in this case" instead of repeating the full raw schema
    (case_id, activity, timestamp, lifecycle_transition, resource,
    amount_requested) every time.
    """
    defaults = {
        "case_id": "1",
        "activity": "A_SUBMITTED",
        "timestamp": "2011-10-01T08:00:00.000+02:00",
        "lifecycle_transition": "COMPLETE",
        "resource": 100.0,
        "amount_requested": 5000,
    }
    filled_rows = [{**defaults, **row} for row in rows]
    return pd.DataFrame(filled_rows)


CLEAN_EVENT_LOG_COLUMNS = ["case_id", "activity", "timestamp", "lifecycle_transition", "is_complete_event"]


def make_clean_event_log(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal post-transform event-log DataFrame for data_quality.py
    and conformance_check.py tests.

    data_quality.py's checks run on the already-transformed schema (real
    datetime timestamps, an is_complete_event flag) -- not on the raw schema
    transform_event_log takes as input. Building it directly here (rather
    than routing through transform_event_log) also sidesteps an unrelated
    interaction: transform_event_log's own drop_duplicates() runs on the full
    raw row (case_id, activity, timestamp, lifecycle_transition, resource,
    amount_requested), a wider key than data_quality's duplicate check (case_id,
    activity, lifecycle_transition, timestamp) -- routing test rows through it
    could silently remove the very duplicate a test is trying to construct.
    """
    defaults = {
        "case_id": "1",
        "activity": "A_SUBMITTED",
        "timestamp": "2011-10-01T08:00:00+02:00",
        "lifecycle_transition": "COMPLETE",
        "is_complete_event": True,
    }
    if not rows:
        empty = pd.DataFrame(columns=CLEAN_EVENT_LOG_COLUMNS)
        return empty.astype({"is_complete_event": bool})

    filled_rows = [{**defaults, **row} for row in rows]
    df = pd.DataFrame(filled_rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df

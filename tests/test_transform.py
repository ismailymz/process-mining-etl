"""Tests for transform.transform_event_log."""

import pandas as pd

from conftest import make_event_log
from transform import transform_event_log


def test_missing_resource_becomes_automated_sentinel():
    """A missing org:resource is a business signal (system-automated step),
    not a data-quality defect -- it must not be silently imputed away."""
    df = make_event_log(
        [
            {"case_id": "1", "activity": "A_SUBMITTED", "resource": None},
            {
                "case_id": "1",
                "activity": "A_PARTLYSUBMITTED",
                "timestamp": "2011-10-01T08:05:00.000+02:00",
                "resource": 100.0,
            },
        ]
    )

    result = transform_event_log(df)

    automated_row = result[result["activity"] == "A_SUBMITTED"].iloc[0]
    assert automated_row["is_automated_step"]
    assert automated_row["resource"] == "SYSTEM_AUTOMATED"

    human_row = result[result["activity"] == "A_PARTLYSUBMITTED"].iloc[0]
    assert not human_row["is_automated_step"]
    assert human_row["resource"] == "100"


def test_amount_category_handles_uniform_amounts_without_crashing():
    """When every case requests the same amount, Q1 == Q3 == upper_fence, so
    the pd.cut bin edges in transform_event_log collapse to duplicate values.
    This degenerate distribution cannot happen in the 13,087-case reference
    data (there's enough spread), but is exactly what a small, uniform test
    fixture naturally produces -- this test asserts the function should
    still return a usable amount_category instead of raising.
    """
    df = make_event_log(
        [
            {"case_id": "1", "activity": "A_SUBMITTED", "amount_requested": 5000},
            {
                "case_id": "2",
                "activity": "A_SUBMITTED",
                "timestamp": "2011-10-02T08:00:00.000+02:00",
                "amount_requested": 5000,
            },
        ]
    )

    result = transform_event_log(df)

    assert "amount_category" in result.columns


def test_timestamps_normalized_to_utc_across_dst_boundary():
    """Two events straddling the EU spring DST transition (local clocks jump
    from 01:xx +01:00 to 03:xx +02:00) must produce the correct *real*
    elapsed time (1 hour) once normalized to UTC, not the naive local
    wall-clock difference (2 hours) that ignoring the offset change would give.
    """
    df = make_event_log(
        [
            {"case_id": "1", "activity": "A_SUBMITTED", "timestamp": "2011-03-27T01:30:00.000+01:00"},
            {"case_id": "1", "activity": "A_PARTLYSUBMITTED", "timestamp": "2011-03-27T03:30:00.000+02:00"},
        ]
    )

    result = transform_event_log(df).sort_values("timestamp")

    elapsed = result["timestamp"].iloc[1] - result["timestamp"].iloc[0]
    assert elapsed == pd.Timedelta(hours=1)

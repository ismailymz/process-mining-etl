"""Tests for process_analysis.compute_transition_thresholds."""

import pandas as pd

from process_analysis import MIN_TRANSITION_SAMPLE_SIZE, compute_transition_thresholds


def _transitions(count: int, transition_name: str = "A -> B", duration_hours: float = 10.0) -> pd.DataFrame:
    return pd.DataFrame({"transition": [transition_name] * count, "duration_hours": [duration_hours] * count})


def test_transition_below_minimum_sample_gets_no_threshold():
    """One occurrence short of MIN_TRANSITION_SAMPLE_SIZE: the threshold must
    be dropped to NaN rather than kept as a number computed from too few
    points to trust."""
    transitions = _transitions(MIN_TRANSITION_SAMPLE_SIZE - 1)
    result = compute_transition_thresholds(transitions)

    row = result.iloc[0]
    assert not row["has_sufficient_sla_sample"]
    assert pd.isna(row["sla_threshold_hours"])


def test_transition_at_minimum_sample_gets_a_threshold():
    """Exactly MIN_TRANSITION_SAMPLE_SIZE occurrences: the >= comparison in
    compute_transition_thresholds means this must count as sufficient."""
    transitions = _transitions(MIN_TRANSITION_SAMPLE_SIZE)
    result = compute_transition_thresholds(transitions)

    row = result.iloc[0]
    assert row["has_sufficient_sla_sample"]
    assert not pd.isna(row["sla_threshold_hours"])

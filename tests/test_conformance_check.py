"""Tests for conformance_check.find_violated_constraints."""

from conformance_check import find_violated_constraints


def test_missing_successor_is_not_a_violation():
    """A_ACCEPTED occurs, but the case is cancelled before ever reaching
    A_FINALIZED or A_APPROVED -- the precedence rules for those must not
    fire just because the successor never happened."""
    activities = ["A_SUBMITTED", "A_PARTLYSUBMITTED", "A_ACCEPTED", "A_CANCELLED"]
    assert find_violated_constraints(activities) == []


def test_missing_predecessor_is_not_a_violation():
    """A_FINALIZED appears without A_ACCEPTED ever occurring in this trace --
    still not flagged, since a constraint only evaluates cases where both
    the predecessor and successor are present."""
    activities = ["A_SUBMITTED", "A_PARTLYSUBMITTED", "A_FINALIZED"]
    assert find_violated_constraints(activities) == []


def test_wrong_order_is_flagged():
    activities = ["A_SUBMITTED", "A_FINALIZED", "A_ACCEPTED"]
    assert find_violated_constraints(activities) == ["A_ACCEPTED must precede A_FINALIZED"]


def test_empty_activity_list_does_not_crash():
    assert find_violated_constraints([]) == []

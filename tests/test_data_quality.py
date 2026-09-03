"""Tests for data_quality.find_duplicate_events, find_invalid_starting_cases,
and find_unusual_length_cases."""

from conftest import make_clean_event_log
from data_quality import find_duplicate_events, find_invalid_starting_cases, find_unusual_length_cases


def test_finds_true_duplicate_event():
    df = make_clean_event_log(
        [
            {"case_id": "1", "activity": "A_SUBMITTED", "lifecycle_transition": "COMPLETE"},
            {"case_id": "1", "activity": "A_SUBMITTED", "lifecycle_transition": "COMPLETE"},
        ]
    )
    assert len(find_duplicate_events(df)) == 1


def test_same_timestamp_different_lifecycle_is_not_a_duplicate():
    """The exact scenario lifecycle_transition was added to the key for:
    a SCHEDULE and a COMPLETE row for the same activity can legitimately
    share a case, activity, and timestamp."""
    df = make_clean_event_log(
        [
            {"case_id": "1", "activity": "W_Completeren aanvraag", "lifecycle_transition": "SCHEDULE"},
            {"case_id": "1", "activity": "W_Completeren aanvraag", "lifecycle_transition": "COMPLETE"},
        ]
    )
    assert len(find_duplicate_events(df)) == 0


def test_single_event_case_starting_correctly_is_not_flagged():
    df = make_clean_event_log([{"case_id": "1", "activity": "A_SUBMITTED"}])
    assert find_invalid_starting_cases(df).empty


def test_single_event_case_starting_incorrectly_is_flagged():
    df = make_clean_event_log([{"case_id": "1", "activity": "A_PARTLYSUBMITTED"}])
    result = find_invalid_starting_cases(df)
    assert result.to_dict() == {"1": "A_PARTLYSUBMITTED"}


def test_empty_event_log_reports_no_unusual_length_cases():
    df = make_clean_event_log([])
    unusual_cases, lower_fence, upper_fence = find_unusual_length_cases(df)
    assert unusual_cases.empty


def test_uniform_case_length_flags_nothing():
    """When every case has the same COMPLETE-event count, IQR is 0 and the
    fences collapse to that count -- no case is outside them."""
    df = make_clean_event_log(
        [
            {"case_id": "1", "activity": "A", "timestamp": "2011-10-01T08:00:00+02:00"},
            {"case_id": "1", "activity": "B", "timestamp": "2011-10-01T09:00:00+02:00"},
            {"case_id": "2", "activity": "A", "timestamp": "2011-10-02T08:00:00+02:00"},
            {"case_id": "2", "activity": "B", "timestamp": "2011-10-02T09:00:00+02:00"},
        ]
    )
    unusual_cases, lower_fence, upper_fence = find_unusual_length_cases(df)
    assert unusual_cases.empty

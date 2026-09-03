"""Transform raw event-log data into a clean analytics-ready dataset.

Source: BPI Challenge 2012 (loan/overdraft application process at a Dutch
financial institution). Unlike the earlier synthetic SAP-style log, this is a
real event log: 24 distinct activities (no fixed step count per case), each
activity can appear as multiple lifecycle sub-events (SCHEDULE/START/COMPLETE),
and some fields have genuine, business-meaningful missing values.
"""

import logging

import numpy as np
import pandas as pd


logger = logging.getLogger(__name__)


REQUIRED_COLUMNS = {
    "case_id",
    "activity",
    "timestamp",
    "lifecycle_transition",
    "resource",
    "amount_requested",
}


def transform_event_log(df: pd.DataFrame) -> pd.DataFrame:
    """Validate, clean, enrich, and order event-log records.

    This represents the transform stage of a small data-engineering ETL job:
    a real, messy event log is made consistent before loading into a database.
    """
    missing_columns = REQUIRED_COLUMNS - set(df.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing_columns))}")

    cleaned_df = df.copy()

    # utc=True normalizes the +01:00/+02:00 offsets caused by Dutch daylight
    # saving time onto one timeline. Without this, a transition duration
    # computed across a DST boundary would be off by an hour.
    cleaned_df["timestamp"] = pd.to_datetime(cleaned_df["timestamp"], errors="coerce", utc=True)

    # case_id, activity, and timestamp are the event's identity: without them
    # the row cannot be placed in a case's trace, so it is unusable.
    cleaned_df = cleaned_df.dropna(subset=["case_id", "activity", "timestamp"])
    cleaned_df = cleaned_df.drop_duplicates()

    # case_id arrives as an integer; treat it as an identifier (string), not a
    # number, so it behaves like the ORD-0001-style ids the rest of the
    # pipeline was written against.
    cleaned_df["case_id"] = cleaned_df["case_id"].astype(str)
    cleaned_df["activity"] = cleaned_df["activity"].str.strip()
    cleaned_df["lifecycle_transition"] = cleaned_df["lifecycle_transition"].str.strip().str.upper()

    # --- resource: missing values are a real business signal, not a data-quality defect ---
    # In this log, ~7% of events have no org:resource, spread across SCHEDULE,
    # START, and COMPLETE alike (not just the system-generated A_SUBMITTED
    # step). That rules out "just one automated step" as the explanation, but
    # the underlying reason is the same: these are events the case-handling
    # system logged on its own (queueing/auto-transitions) rather than a
    # person acting on the file. Silently imputing "Unknown" like a missing
    # region/customer would would hide that distinction. Instead we keep it
    # explicit with a flag plus a named sentinel, so downstream analysis can
    # measure automation rate or separate human workload from system activity
    # instead of just seeing an unexplained gap.
    is_automated_step = cleaned_df["resource"].isna()
    resource_id = cleaned_df["resource"].astype("Int64").astype(str)
    cleaned_df["resource"] = resource_id.where(~is_automated_step, "SYSTEM_AUTOMATED")
    cleaned_df["is_automated_step"] = is_automated_step

    # --- amount_requested: a case-level attribute, validated at the case level ---
    # AMOUNT_REQ is set once per loan application and repeated on every event
    # row of that case_id, so it must be validated and aggregated per case,
    # not per event (a case with 40 events would otherwise count 40x in any
    # statistic, e.g. an IQR/quantile calculation would be silently skewed
    # toward busy cases).
    cleaned_df["amount_requested"] = pd.to_numeric(cleaned_df["amount_requested"], errors="coerce")
    # A requested loan amount cannot be negative; treat negative values as
    # invalid data rather than a real amount.
    cleaned_df.loc[cleaned_df["amount_requested"] < 0, "amount_requested"] = np.nan
    # Collapse back to one consistent value per case (median tolerates an
    # occasional corrupted row without being pulled off by a single outlier).
    cleaned_df["amount_requested"] = cleaned_df.groupby("case_id")["amount_requested"].transform("median")

    # Outlier / size boundaries are computed once, on a case-deduplicated
    # series, so every case contributes exactly one data point to the
    # quartiles -- avoiding the same over-counting problem described above.
    case_level_amounts = cleaned_df.drop_duplicates("case_id")["amount_requested"]
    first_quartile = case_level_amounts.quantile(0.25)
    third_quartile = case_level_amounts.quantile(0.75)
    interquartile_range = third_quartile - first_quartile
    lower_fence = first_quartile - 1.5 * interquartile_range
    upper_fence = third_quartile + 1.5 * interquartile_range

    cleaned_df["is_amount_outlier"] = (cleaned_df["amount_requested"] < lower_fence) | (
        cleaned_df["amount_requested"] > upper_fence
    )

    # amount_category reuses the same quartile/fence values already computed
    # for outlier detection, rather than inventing separate round-number cut
    # points -- so "Very Large" lines up exactly with what is already flagged
    # as a statistical outlier, instead of two disconnected definitions of
    # "large". Bin edges (from the case-level describe()): Q1=5,000,
    # Q3=17,620, upper fence=36,550.
    if interquartile_range > 0:
        cleaned_df["amount_category"] = pd.cut(
            cleaned_df["amount_requested"],
            bins=[-np.inf, first_quartile, third_quartile, upper_fence, np.inf],
            labels=["Small", "Medium", "Large", "Very Large"],
        )
    else:
        # Degenerate distribution (every case requests the same amount, or
        # the sample is too small/uniform for quartiles to differ) -- there's
        # no meaningful size distinction to draw, so every case gets the same
        # neutral category instead of crashing pd.cut on duplicate bin edges.
        cleaned_df["amount_category"] = "Medium"

    # --- lifecycle_transition: keep every state, don't collapse to COMPLETE-only ---
    # Dropping SCHEDULE/START here would throw away the ability to ever
    # measure queue time (SCHEDULE -> START, waiting for a free resource) versus
    # processing time (START -> COMPLETE, actual handling time) -- a core
    # process-mining distinction. Filtering to COMPLETE-only is a valid choice
    # for control-flow/bottleneck analysis, but that is an analysis-stage
    # decision, not a transform-stage one; we only add a flag so either view
    # is possible downstream.
    cleaned_df["is_complete_event"] = cleaned_df["lifecycle_transition"].eq("COMPLETE")

    cleaned_df["event_date"] = cleaned_df["timestamp"].dt.date

    result = cleaned_df.sort_values(["case_id", "timestamp"]).reset_index(drop=True)
    dropped_rows = len(df) - len(result)
    logger.info(
        "Transformed %d rows from %d input rows (%d dropped for missing identity fields or duplicates).",
        len(result),
        len(df),
        dropped_rows,
    )
    return result

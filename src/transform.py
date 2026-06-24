"""Transform raw event-log data into a clean analytics-ready dataset."""

import pandas as pd


REQUIRED_COLUMNS = {
    "case_id",
    "activity",
    "timestamp",
    "region",
    "customer",
    "material_id",
    "quantity",
    "priority",
}


def transform_event_log(df: pd.DataFrame) -> pd.DataFrame:
    """Validate, clean, enrich, and order event-log records.

    This represents the transform stage of a small data-engineering ETL job:
    raw SAP-like records are made consistent before loading into a database.
    """
    missing_columns = REQUIRED_COLUMNS - set(df.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing_columns))}")

    cleaned_df = df.copy()
    cleaned_df["timestamp"] = pd.to_datetime(cleaned_df["timestamp"], errors="coerce")

    # Rows without an event identity or valid timestamp cannot be used in process analysis.
    cleaned_df = cleaned_df.dropna(subset=["case_id", "activity", "timestamp"])
    cleaned_df = cleaned_df.drop_duplicates()

    # Fill remaining descriptive fields with explicit, analysis-friendly defaults.
    cleaned_df["region"] = cleaned_df["region"].fillna("Unknown")
    cleaned_df["customer"] = cleaned_df["customer"].fillna("Unknown")
    cleaned_df["material_id"] = cleaned_df["material_id"].fillna("Unknown")
    cleaned_df["priority"] = cleaned_df["priority"].fillna("Normal")
    cleaned_df["quantity"] = pd.to_numeric(cleaned_df["quantity"], errors="coerce").fillna(0)

    cleaned_df["event_date"] = cleaned_df["timestamp"].dt.date
    cleaned_df["is_high_priority"] = cleaned_df["priority"].eq("High")

    return cleaned_df.sort_values(["case_id", "timestamp"]).reset_index(drop=True)

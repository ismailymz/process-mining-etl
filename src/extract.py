"""Extract raw SAP-like event-log data for the ETL pipeline."""

from pathlib import Path

import pandas as pd


def extract_event_log(file_path: str | Path) -> pd.DataFrame:
    """Read the raw event log CSV and return it as a DataFrame."""
    return pd.read_csv(file_path)

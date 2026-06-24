"""Load transformed event-log data into SQLite."""

from pathlib import Path
import sqlite3

import pandas as pd


def load_to_sqlite(df: pd.DataFrame, db_path: str | Path, table_name: str) -> None:
    """Replace the target SQLite table with the transformed event log."""
    database_path = Path(db_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(database_path) as connection:
        df.to_sql(table_name, connection, if_exists="replace", index=False)

"""Run the Extract -> Transform -> Load pipeline for the event log."""

from pathlib import Path

from extract import extract_event_log
from load import load_to_sqlite
from transform import transform_event_log


def main() -> None:
    """Execute a simple ETL job similar to a data-engineering workflow."""
    project_root = Path(__file__).resolve().parents[1]
    raw_file_path = project_root / "data" / "raw" / "event_log.csv"
    processed_file_path = project_root / "data" / "processed" / "event_log_clean.csv"
    database_path = project_root / "database.db"
    table_name = "event_log"

    raw_event_log = extract_event_log(raw_file_path)
    print(f"Extracted rows: {len(raw_event_log)}")

    cleaned_event_log = transform_event_log(raw_event_log)
    print(f"Transformed rows: {len(cleaned_event_log)}")

    processed_file_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned_event_log.to_csv(processed_file_path, index=False)
    print(f"Saved cleaned CSV: {processed_file_path}")

    load_to_sqlite(cleaned_event_log, database_path, table_name)
    print(f"Loaded table: {table_name}")


if __name__ == "__main__":
    main()

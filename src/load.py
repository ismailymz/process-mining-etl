"""Load transformed event-log data into SQLite."""

import logging
from pathlib import Path
import sqlite3
from typing import Union

import pandas as pd


logger = logging.getLogger(__name__)


# The natural composite identity of one BPI2012 event: a case can only log
# one lifecycle transition of one activity at one instant. This is the same
# key data_quality.py already uses to detect duplicate events in application
# code -- enforcing it here as a UNIQUE index means the database itself
# rejects a genuine duplicate rather than relying on every caller to have run
# that check first.
UNIQUE_EVENT_COLUMNS = ("case_id", "activity", "lifecycle_transition", "timestamp")


def load_to_sqlite(df: pd.DataFrame, db_path: Union[str, Path], table_name: str) -> None:
    """Replace the target SQLite table with the transformed event log.

    This is a full-refresh load, not incremental: BPI2012 is a closed,
    one-time historical export with no ongoing source to poll for new rows,
    so there is nothing genuine to load incrementally here. What full refresh
    still needs, though, is to not corrupt `table_name` if the load itself
    fails partway through -- so this writes to a staging table first and
    swaps it in, all inside one transaction, rather than writing
    `table_name` directly:

    - pandas' to_sql(if_exists="replace") drops the existing table before
      inserting the new rows in chunks. A failure partway through (a bad
      value, a killed process, a full disk, or -- with the UNIQUE index
      below -- a genuine duplicate) would otherwise leave `table_name` empty
      or half-populated for any reader running in between.
    - Building the new data in a separate staging table and only swapping it
      into `table_name` at the very end (inside the same transaction as the
      staging writes) means `table_name` is always either the previous good
      load or the complete new one -- never a partial one. If anything above
      fails, the transaction rolls back and `table_name` is left exactly as
      it was before this call.
    """
    database_path = Path(db_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    staging_table_name = f"{table_name}__staging"
    unique_index_name = f"idx_{table_name}_unique_event"

    connection = sqlite3.connect(database_path)
    try:
        connection.execute("BEGIN")

        # Defensive cleanup: a previous run that crashed after writing the
        # staging table but before the swap would leave one behind.
        connection.execute(f'DROP TABLE IF EXISTS "{staging_table_name}"')
        # The index is named after the final table, not the staging table, so
        # it reads naturally once swapped in. That name currently belongs to
        # the live table this run is about to replace, so it must be freed
        # here before the same name can be reused on the staging table below.
        connection.execute(f'DROP INDEX IF EXISTS "{unique_index_name}"')

        df.to_sql(staging_table_name, connection, if_exists="replace", index=False)

        # If the transformed data ever contains a genuine duplicate event
        # (same case, activity, lifecycle stage, and timestamp -- a
        # transform.py bug or a corrupted source export), this raises
        # sqlite3.IntegrityError. The exception below rolls the whole
        # transaction back, so the previous good `table_name` is left
        # completely untouched instead of silently accepting corrupt data.
        columns = ", ".join(UNIQUE_EVENT_COLUMNS)
        connection.execute(f'CREATE UNIQUE INDEX "{unique_index_name}" ON "{staging_table_name}" ({columns})')

        # SQLite's rename carries the table's rows and its index over as-is;
        # nothing further needs to reference the staging name afterward.
        connection.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        connection.execute(f'ALTER TABLE "{staging_table_name}" RENAME TO "{table_name}"')

        connection.commit()
        logger.info("Loaded table '%s' with %d rows.", table_name, len(df))
    except Exception as err:
        connection.rollback()
        # ERROR, not just a re-raised exception: this is the one place the
        # load can fail after already touching the database (a genuine
        # duplicate tripping the UNIQUE index, a disk error mid-write), so
        # it's worth a persisted record of exactly what happened and that
        # `table_name` was left untouched -- distinct from a routine
        # completion, this is the pipeline failing to do its job.
        logger.error("Load into '%s' failed and was rolled back: %s", table_name, err)
        # Verified empirically (not assumed): Python's sqlite3 module does
        # not reliably undo a DDL statement (here, the CREATE TABLE issued
        # internally by to_sql) via rollback() the way it does plain DML.
        # `table_name` was confirmed untouched either way, but the staging
        # table itself can survive the rollback -- clean it up explicitly
        # rather than depending on transactional DDL semantics that don't
        # hold here. The next call would also self-heal via the DROP TABLE
        # IF EXISTS at the top, but there is no reason to leave debris until then.
        connection.execute(f'DROP TABLE IF EXISTS "{staging_table_name}"')
        connection.commit()
        raise
    finally:
        connection.close()

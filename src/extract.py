"""Extract raw event-log data for the ETL pipeline."""

import logging
from pathlib import Path
from typing import Union

import pandas as pd


# Library module: only gets a logger, never configures logging itself (see
# logging_config.py). main.py, the entry point that imports this module,
# calls configure_logging() once before anything here runs.
logger = logging.getLogger(__name__)


# The pipeline cannot do anything meaningful without at least these columns
# identifying "what happened, for which case, when". This is only a cheap
# sanity check to fail fast on an obviously wrong file -- full schema
# validation (all required business columns) stays transform.py's
# responsibility, so it isn't duplicated in two places.
MINIMUM_IDENTITY_COLUMNS = {"case_id", "activity", "timestamp"}


class EventLogExtractionError(Exception):
    """Raised when the raw event log cannot be read into a usable DataFrame.

    A dedicated exception type -- rather than letting pandas' own exceptions
    propagate as-is -- gives callers (e.g. main.py) one stable type to catch
    for "the extract stage failed", regardless of the underlying cause. That
    decouples the pipeline's error handling from pandas' internal exception
    types, which can change across pandas versions or if the source format
    changes later (e.g. Parquet instead of CSV). The original exception is
    still attached with `from err` so its traceback is not lost for debugging.
    """


def extract_event_log(file_path: Union[str, Path]) -> pd.DataFrame:
    """Read the raw event log CSV and return it as a DataFrame.

    Raises EventLogExtractionError with a specific, human-readable reason if
    the file is missing, empty, unparsable, or clearly not an event log.
    """
    path = Path(file_path)

    # Checked explicitly (rather than relying on pandas' own FileNotFoundError)
    # so the message can name the exact expected path -- useful when the
    # pipeline is run from a different working directory than expected.
    if not path.exists():
        message = (
            f"Raw event log not found at '{path}'. Expected a CSV file at this "
            "path -- check that the source file was placed there before running the pipeline."
        )
        # ERROR, not just a raised exception: without this, a scheduled/
        # unattended run that isn't watched interactively leaves no record of
        # why the pipeline stopped, only whatever the caller does with the
        # exception (which may just be a crash with no persisted trace).
        logger.error(message)
        raise EventLogExtractionError(message)

    try:
        event_log = pd.read_csv(path)
    except pd.errors.EmptyDataError as err:
        # Raised by pandas when the file has zero bytes / no header at all.
        message = f"Raw event log at '{path}' is empty (no header/columns found)."
        logger.error(message)
        raise EventLogExtractionError(message) from err
    except pd.errors.ParserError as err:
        # Raised by pandas on malformed CSV content, e.g. inconsistent column
        # counts across rows. The original message already names the
        # offending line, so it's included rather than replaced.
        message = f"Raw event log at '{path}' could not be parsed as CSV: {err}"
        logger.error(message)
        raise EventLogExtractionError(message) from err

    # A file can parse successfully but still have a header with zero data
    # rows (e.g. an export that failed midway). Downstream stages assume at
    # least some events exist, so this is caught here rather than surfacing
    # as a confusing empty-result error several steps later.
    if event_log.empty:
        message = f"Raw event log at '{path}' has a header but no data rows."
        logger.error(message)
        raise EventLogExtractionError(message)

    if MINIMUM_IDENTITY_COLUMNS.isdisjoint(event_log.columns):
        message = (
            f"Raw event log at '{path}' has none of the expected identity columns "
            f"({', '.join(sorted(MINIMUM_IDENTITY_COLUMNS))}). This looks like the wrong file."
        )
        logger.error(message)
        raise EventLogExtractionError(message)

    logger.info("Extracted %d rows from '%s'.", len(event_log), path)
    return event_log

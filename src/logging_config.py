"""Central logging configuration for this project's pipeline entry points.

Only entry-point scripts (the ones with `if __name__ == "__main__":`) call
configure_logging() -- library modules (extract.py, transform.py, load.py)
just take a `logger = logging.getLogger(__name__)` and use it. This follows
the standard Python convention: a library should never configure logging
handlers itself, since doing so could clobber a level/destination the
importing application already chose; only the application (here, each
standalone script) decides how logs are actually handled.
"""

from __future__ import annotations

import logging
from pathlib import Path


LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(log_to_file: bool = True, level: int = logging.INFO) -> None:
    """Configure the root logger once, at process start, for a CLI script.

    Console output stays for a human running the script interactively;
    the optional file handler under logs/pipeline.log is what makes the run
    inspectable afterward (e.g. "did last night's scheduled run log any
    WARNING/ERROR lines") without having to capture stdout yourself.
    """
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if log_to_file:
        project_root = Path(__file__).resolve().parents[1]
        log_dir = project_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_dir / "pipeline.log", encoding="utf-8"))

    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=DATE_FORMAT, handlers=handlers, force=True)

"""Convert the original BPI Challenge 2012 XES export into the flat CSV
schema (case_id, activity, timestamp, lifecycle_transition, resource,
amount_requested) used by this project's ETL pipeline.

This is the migration script that produced data/raw/event_log.csv when the
project moved from the synthetic SAP-like log (see
scripts/legacy/generate_data.py) to the real BPI2012 event log. It is not
part of the active pipeline (extract.py reads the already-converted CSV) and
does not need to be re-run unless data/raw/event_log.csv is lost -- it is
kept as a reproducible reference for how that conversion was done.

Reads directly from the original zip in data/raw/ (no manual unzip needed):
AMOUNT_REQ and concept:name are trace-level attributes in XES (one loan
amount and case id per case), so they are broadcast onto every event row of
that case here; case_id, activity, timestamp, lifecycle_transition, and
resource are per-event attributes read as-is (resource is left blank when
org:resource is absent from an event, which transform.py later treats as a
real business signal, not a defect -- see transform.py).
"""

from __future__ import annotations

import csv
import gzip
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

XES_NAMESPACE = "{http://www.xes-standard.org/}"
ZIP_ENTRY_NAME = "BPI_Challenge_2012.xes.gz"


def local_tag(tag: str) -> str:
    """Strip the XES XML namespace prefix from an element tag."""
    return tag.replace(XES_NAMESPACE, "")


def convert(zip_path: Path, output_path: Path) -> tuple[int, int]:
    """Convert the zipped XES log at `zip_path` into a flat CSV at `output_path`.

    Returns (trace_count, event_count) for the caller to report.
    """
    trace_count = 0
    event_count = 0

    with zipfile.ZipFile(zip_path) as archive, output_path.open("w", newline="", encoding="utf-8") as out_file:
        writer = csv.writer(out_file)
        writer.writerow(["case_id", "activity", "timestamp", "lifecycle_transition", "resource", "amount_requested"])

        with archive.open(ZIP_ENTRY_NAME) as gz_entry, gzip.GzipFile(fileobj=gz_entry) as xes_stream:
            for _, element in ET.iterparse(xes_stream, events=("end",)):
                if local_tag(element.tag) != "trace":
                    continue

                case_id = None
                amount_requested = None
                for child in element:
                    if local_tag(child.tag) != "string":
                        continue
                    if child.get("key") == "concept:name":
                        case_id = child.get("value")
                    elif child.get("key") == "AMOUNT_REQ":
                        amount_requested = child.get("value")

                for event_element in element.findall(f"{XES_NAMESPACE}event"):
                    activity = timestamp = lifecycle_transition = resource = None
                    for attribute in event_element:
                        key = attribute.get("key")
                        value = attribute.get("value")
                        if key == "concept:name":
                            activity = value
                        elif key == "time:timestamp":
                            timestamp = value
                        elif key == "lifecycle:transition":
                            lifecycle_transition = value
                        elif key == "org:resource":
                            resource = value
                    writer.writerow([case_id, activity, timestamp, lifecycle_transition, resource, amount_requested])
                    event_count += 1

                trace_count += 1
                element.clear()

    return trace_count, event_count


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    zip_path = project_root / "data" / "raw" / "BPI Challenge 2012_1_all.zip"
    output_path = project_root / "data" / "raw" / "bpi2012_event_log.csv"

    trace_count, event_count = convert(zip_path, output_path)
    print(f"Converted {trace_count} traces (cases) and {event_count} events -> {output_path}")


if __name__ == "__main__":
    main()

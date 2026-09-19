"""
Readers for the three intake formats: CSV, JSON, XML.

Each reader's only job is to turn a file into `list[dict]`. All validation and
coercion happens in normalize.py -- one place, not three. That separation (read
vs. validate) is what keeps this maintainable when a fourth format shows up.

Why all three formats matter for this problem statement: intelligence feeds do
not agree on a format. A pcap export, a chain-analytics dump and an internal
database extract will each arrive differently. Accepting one format would mean
the tool only works with one source.

Usage (via the pipeline):
    df, report = load_any(Path("data/transactions.csv"))
"""

from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pandas as pd

from ingestion.normalize import LoadReport, normalize_records

SUPPORTED_SUFFIXES = {".csv", ".txt", ".json", ".xml"}


def _read_csv(path: Path) -> list[dict[str, Any]]:
    """Read CSV. We use the csv module (not pandas.read_csv) so that every value
    stays a plain string and no silent type coercion happens before validation.
    pandas would happily turn '1e5' into a float or mangle an address; we want
    the raw text so normalize_row can make the decision."""
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        # Sniff the delimiter so we accept both ',' and ';' exports.
        sample = fh.read(8192)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(fh, dialect=dialect)
        # Strip whitespace from header names -- exports often pad them.
        return [
            {(k or "").strip(): v for k, v in row.items()}
            for row in reader
        ]


def _read_json(path: Path) -> list[dict[str, Any]]:
    """Read JSON. Accepts three shapes we've seen in real exports:
        [ {...}, {...} ]                     -- bare array
        { "transactions": [ {...} ] }        -- wrapped under a key
        { "data": { "records": [ {...} ] } } -- nested wrapper
    Being liberal here costs little and saves a demo.
    """
    data = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]

    if isinstance(data, dict):
        # Look one level deep for the first list-of-dicts we can find.
        for value in data.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value
            if isinstance(value, dict):
                for nested in value.values():
                    if isinstance(nested, list) and nested and isinstance(nested[0], dict):
                        return nested
        # A single record, not a list.
        return [data]

    return []


def _read_xml(path: Path) -> list[dict[str, Any]]:
    """Read XML. Any repeated child element is treated as a record; each of that
    element's children becomes a field. This handles
        <transactions><transaction>...</transaction></transactions>
    and
        <records><record>...</record></records>
    without hard-coding tag names."""
    tree = ET.parse(path)
    root = tree.getroot()

    # Find the first element that has element children (the record container).
    container = root
    for _ in range(3):  # a little tolerance for wrapper elements
        children = [c for c in container if len(c)]
        if not children:
            break
        tag_counts: dict[str, int] = {}
        for child in children:
            tag_counts[child.tag] = tag_counts.get(child.tag, 0) + 1
        repeated = max(tag_counts.items(), key=lambda kv: kv[1])
        if repeated[1] > 1:
            container = None
            record_tag = repeated[0]
            break
        container = children[0]
    else:
        record_tag = None
        container = None

    if container is None:
        records = [el for el in root.iter() if el.tag == record_tag]
    else:
        records = [el for el in container if len(el)]

    rows: list[dict[str, Any]] = []
    for record in records:
        row: dict[str, Any] = {}
        for child in record:
            # <input_addresses><addr>..</addr><addr>..</addr></input_addresses>
            # becomes "addr|addr" so normalize.py's array parser handles it the
            # same way it handles a CSV cell.
            grand_children = [c for c in child if len(c)]
            if grand_children:
                row[child.tag] = "|".join((gc.text or "").strip() for gc in grand_children)
            else:
                row[child.tag] = (child.text or "").strip()
        if row:
            rows.append(row)
    return rows


_READERS = {
    ".csv": _read_csv,
    ".txt": _read_csv,
    ".json": _read_json,
    ".xml": _read_xml,
}


def load_raw(path: Path) -> tuple[list[dict[str, Any]], str]:
    """Dispatch on file extension. Returns (records, format_name)."""
    suffix = path.suffix.lower()
    reader = _READERS.get(suffix)
    if reader is None:
        raise ValueError(
            f"unsupported file type '{suffix}' -- expected one of "
            f"{', '.join(sorted(SUPPORTED_SUFFIXES))}"
        )
    return reader(path), suffix.lstrip(".")


def load_any(path: Path | str) -> tuple[pd.DataFrame, LoadReport]:
    """The one entry point the rest of the system uses.

    Returns the canonical DataFrame plus a LoadReport describing exactly what
    was accepted and what was thrown away.
    """
    path = Path(path)
    report = LoadReport(source=path.name)

    if not path.exists():
        raise FileNotFoundError(f"no such file: {path}")

    records, fmt = load_raw(path)
    report.format = fmt
    df = normalize_records(records, report)
    return df, report


def load_dataframe(df: pd.DataFrame, source: str = "inline") -> tuple[pd.DataFrame, LoadReport]:
    """Same contract as load_any, for callers that already hold a DataFrame
    (e.g. the API receiving an upload it has already parsed, or a test)."""
    report = LoadReport(source=source, format="dataframe")
    clean = normalize_records(df.to_dict("records"), report)
    return clean, report

"""
Readers for the intake formats: CSV, JSON, XML, and SQLite.

Each reader's only job is to turn a file into a DataFrame. All validation and
coercion happens in normalize.py -- one place, not four. That separation (read
vs. validate) is what keeps this maintainable when a fifth format shows up.

Why all of these matter for this problem statement: intelligence feeds do not
agree on a format. A pcap export, a chain-analytics dump, an internal database
extract and a seized SQLite file will each arrive differently. Accepting one
format would mean the tool only works with one source.

WHY SQLite AND NOT A .SQL DUMP
------------------------------
An agency handing over "the database" hands over either a SQLite file or a text
dump of INSERT statements. We read the former properly, via the stdlib `sqlite3`
module, in read-only mode.

We deliberately do NOT parse `.sql` dump text. A hand-rolled SQL parser has to
cope with quoting, escapes, multi-row VALUES, comments, encoding and vendor
dialect drift, and every one of those is a silent-corruption bug waiting in the
intake path of a criminal investigation. `sqlite3 dump.sql | sqlite3 out.db`
converts a dump correctly in one command, so the correct engineering answer is to
require the database rather than to half-implement a parser.

WHY READERS RETURN DATAFRAMES
-----------------------------
The previous version returned `list[dict]` for every row, which at 1M rows means
a million Python dicts -- on the order of a gigabyte of pure overhead before any
validation happens. Readers now return a DataFrame, and normalization works
column-wise on it.

For CSV this also means we keep the deliberate choice from before: read every
cell as TEXT (`dtype=str`) so nothing is coerced before validation. pandas would
otherwise turn '1e5' into a float and destroy the evidence that the source file
was malformed.

Usage (via the pipeline):
    df, report = load_any(Path("data/transactions.csv"))
    df, report = load_any(Path("seized.db"), table="traffic")
"""

from __future__ import annotations

import csv
import json
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pandas as pd

from ingestion.normalize import LoadReport, normalize_records

SUPPORTED_SUFFIXES = {".csv", ".txt", ".json", ".xml", ".sqlite", ".sqlite3", ".db"}

SQLITE_SUFFIXES = {".sqlite", ".sqlite3", ".db"}

# Table names that look like transaction traffic, best first. Used to choose a
# table when the database holds several.
_TABLE_HINTS = ("transaction", "transactions", "traffic", "tx", "txs", "flow", "flows", "records")


def _read_csv(path: Path) -> pd.DataFrame:
    """Read CSV as text, sniffing the delimiter.

    `dtype=str` and `keep_default_na=False` are the important part: every cell
    stays exactly as written, so 'N/A', '-1' and '1e5' reach the validator
    intact and can be rejected with a reason. Letting pandas guess types here
    would erase the very evidence the validator needs.
    """
    # Sniff the delimiter from a sample, then parse with pandas' C engine.
    # Passing sep=None makes pandas use its slow Python engine for the WHOLE
    # file just to sniff the first few kilobytes -- so we sniff ourselves and
    # hand it an explicit separator.
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            sample = handle.read(8192)
        separator = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except (OSError, csv.Error):
        separator = ","

    frame = pd.read_csv(
        path, dtype=str, keep_default_na=False, sep=separator, encoding="utf-8-sig",
    )
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame


def _read_json(path: Path) -> pd.DataFrame:
    """Read JSON. Accepts three shapes we've seen in real exports:
        [ {...}, {...} ]                     -- bare array
        { "transactions": [ {...} ] }        -- wrapped under a key
        { "data": { "records": [ {...} ] } } -- nested wrapper
    Being liberal here costs little and saves a demo.
    """
    data = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(data, list):
        records = [row for row in data if isinstance(row, dict)]
    elif isinstance(data, dict):
        records = None
        # Look one level deep for the first list-of-dicts we can find.
        for value in data.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                records = value
                break
            if isinstance(value, dict):
                for nested in value.values():
                    if isinstance(nested, list) and nested and isinstance(nested[0], dict):
                        records = nested
                        break
            if records is not None:
                break
        if records is None:
            # A single record, not a list.
            records = [data]
    else:
        records = []

    return pd.DataFrame(records)


def _read_xml(path: Path) -> pd.DataFrame:
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
    return pd.DataFrame(rows)


def _pick_sqlite_table(connection: sqlite3.Connection, tables: list[str]) -> str:
    """Choose which table holds the transaction records.

    Preference order, most explicit first: a name that looks like traffic, then
    the table with the most rows. Deterministic either way, because "whichever
    table the database happened to list first" is how a demo picks the wrong
    table and reports a clean analysis of the schema metadata.
    """
    named = [table for table in tables
             if any(hint in table.lower() for hint in _TABLE_HINTS)]
    candidates = named or tables

    def row_count(table: str) -> int:
        try:
            cursor = connection.execute(f'SELECT COUNT(*) FROM "{table}"')
            return int(cursor.fetchone()[0])
        except sqlite3.Error:
            return 0

    scored = [(row_count(table), table) for table in candidates]
    scored.sort(reverse=True)
    return scored[0][1]


def _read_sqlite(path: Path, table: str | None = None) -> pd.DataFrame:
    """Read a table from a SQLite database, without modifying it.

    Opened read-only via a URI so that pointing the tool at a seized database
    can never write to it -- an evidence-handling requirement, not a nicety.
    """
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        tables = [
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view') "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        if not tables:
            raise ValueError(f"no tables found in {path.name}")
        chosen = table or _pick_sqlite_table(connection, tables)
        if chosen not in tables:
            raise ValueError(
                f"table '{chosen}' not found in {path.name} -- available: "
                f"{', '.join(tables)}"
            )
        # dtype is left to sqlite3, which returns native types for typed columns;
        # text columns stay text. Validation handles either.
        frame = pd.read_sql_query(f'SELECT * FROM "{chosen}"', connection)
    finally:
        connection.close()
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame


_READERS = {
    ".csv": _read_csv,
    ".txt": _read_csv,
    ".json": _read_json,
    ".xml": _read_xml,
}


def load_raw(path: Path, table: str | None = None) -> tuple[pd.DataFrame, str]:
    """Dispatch on file extension. Returns (records_frame, format_name)."""
    suffix = path.suffix.lower()

    if suffix in SQLITE_SUFFIXES:
        return _read_sqlite(path, table), "sqlite"

    reader = _READERS.get(suffix)
    if reader is None:
        raise ValueError(
            f"unsupported file type '{suffix}' -- expected one of "
            f"{', '.join(sorted(SUPPORTED_SUFFIXES))}. "
            "(A .sql text dump is not accepted: convert it first with "
            "'sqlite3 dump.sql | sqlite3 out.db'.)"
        )
    return reader(path), suffix.lstrip(".")


def load_any(
    path: Path | str,
    report: LoadReport | None = None,
    table: str | None = None,
) -> tuple[pd.DataFrame, LoadReport]:
    """The one entry point the rest of the system uses.

    Returns the canonical DataFrame plus a LoadReport describing exactly what
    was accepted and what was thrown away.

    `report` may be passed in so a caller can see incremental progress on a
    large file; otherwise a fresh one is created.
    """
    path = Path(path)
    report = report or LoadReport(source=path.name)
    report.source = path.name

    if not path.exists():
        raise FileNotFoundError(f"no such file: {path}")

    frame, fmt = load_raw(path, table=table)
    report.format = fmt
    return normalize_records(frame, report), report


def load_dataframe(df: pd.DataFrame, source: str = "inline") -> tuple[pd.DataFrame, LoadReport]:
    """Same contract as load_any, for callers that already hold a DataFrame
    (e.g. the API receiving an upload it has already parsed, or a test)."""
    report = LoadReport(source=source, format="dataframe")
    return normalize_records(df, report), report

"""
Monitoring state: identity that survives between runs, and a history to diff.

WHY THIS FILE EXISTS
--------------------
Everything before this point is a stateless batch transform: file in, scores
out, and no memory whatsoever. Run it twice and it has no idea it has seen any
of it before. That is the Analysis half of "Monitoring & Analysis". This module
is the other half.

SQLite via the standard library, because the target is an air-gapped Linux host:
one file, no server, no dependency to vendor, and it survives a machine
restart. DuckDB or Postgres would both be better databases and both worse
choices here.

THE PROBLEM THIS SOLVES, WHICH IS NOT OBVIOUS
---------------------------------------------
Monitoring requires stable identity across time. Cluster ids from R1 are derived
from cluster CONTENT (the lexicographically smallest address), so the same
cluster gets the same key in any run. That is necessary but NOT sufficient,
because a cluster CHANGES: a wallet that spends a new address joins that address
into its cluster, and if the newly-joined address happens to sort before the old
anchor, the anchor moves and the key changes.

The cluster did not become a different wallet. It just renamed itself.

So identity is PINNED. The first time an address is seen, it is bound to an
entity key for good, in `address_entity`. A later cluster inherits the key of the
addresses it already contains:

    new batch -> cluster addresses -> do any already have a key?
        no  -> new entity, key derived from its anchor
        yes -> inherit; the pinned key wins over the derived one

AND THE CASE THAT MATTERS MOST: MERGING
---------------------------------------
When a new transaction co-spends addresses from two previously separate clusters,
those clusters are now provably one entity. That is not a nuisance to paper over
-- it is intelligence. Two operations being linked is a finding, and it is the
kind of thing this system exists to notice.

So a merge keeps the key of the surviving entity (the one seen first,
deterministically), absorbs the other, re-points its addresses, and emits a
CLUSTER_MERGE event that an analyst can see.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- One row per ingested batch. The raw file stays on disk; we index it.
CREATE TABLE IF NOT EXISTS windows (
    window_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT    NOT NULL UNIQUE,
    start_ts    TEXT    NOT NULL,
    end_ts      TEXT    NOT NULL,
    path        TEXT    NOT NULL,
    n_tx        INTEGER NOT NULL,
    n_entities  INTEGER NOT NULL
);

-- Address -> pinned entity key. This table IS the identity layer.
CREATE TABLE IF NOT EXISTS address_entity (
    address         TEXT PRIMARY KEY,
    entity_key      TEXT NOT NULL,
    first_window_id INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_address_entity_key ON address_entity(entity_key);

-- Entity -> canonical key, which differs from the derived key after a merge.
CREATE TABLE IF NOT EXISTS entity_alias (
    alias_key       TEXT PRIMARY KEY,
    canonical_key   TEXT NOT NULL,
    resolved_window INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS entities (
    entity_key       TEXT PRIMARY KEY,
    first_window_id  INTEGER NOT NULL,
    last_window_id   INTEGER NOT NULL,
    address_count    INTEGER NOT NULL DEFAULT 0,
    last_risk        INTEGER,
    last_band        TEXT,
    role             TEXT,
    community_id     INTEGER
);

-- Per-window prediction, plus the feature vector it was computed from, which is
-- what makes "risk moved because country_count went 1 -> 3" answerable.
CREATE TABLE IF NOT EXISTS scores (
    entity_key   TEXT    NOT NULL,
    window_id    INTEGER NOT NULL,
    risk         INTEGER NOT NULL,
    anomaly      REAL,
    band         TEXT    NOT NULL,
    features     TEXT    NOT NULL,
    PRIMARY KEY (entity_key, window_id)
);
CREATE INDEX IF NOT EXISTS idx_scores_window ON scores(window_id);

CREATE TABLE IF NOT EXISTS events (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    window_id   INTEGER NOT NULL,
    entity_key  TEXT    NOT NULL,
    type        TEXT    NOT NULL,
    severity    TEXT    NOT NULL,
    detail      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_window ON events(window_id);

-- An alert is a LEAD with a memory: one row per entity, updated in place, so a
-- wallet that stays critical for ten windows produces one alert whose history
-- grows rather than ten alerts nobody can triage.
CREATE TABLE IF NOT EXISTS alerts (
    alert_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_key    TEXT    NOT NULL UNIQUE,
    first_window  INTEGER NOT NULL,
    last_window   INTEGER NOT NULL,
    peak_risk     INTEGER NOT NULL,
    current_risk  INTEGER NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'new',
    assignee      TEXT,
    note          TEXT
);
"""

ALERT_STATUSES = ("new", "acknowledged", "investigating", "closed_false_positive", "closed_escalated")


@dataclass
class WindowRecord:
    window_id: int
    label: str
    start_ts: str
    end_ts: str
    path: str
    n_tx: int
    n_entities: int


@dataclass
class MergeEvent:
    survivor: str
    absorbed: list[str]


@dataclass
class Resolution:
    """Outcome of pinning one window's clusters onto the identity registry."""

    address_to_entity: dict[str, str]
    new_entities: list[str]
    merges: list[MergeEvent]
    relabelled: int   # clusters whose derived key was replaced by a pinned one
    # derived key -> canonical key. Needed so the correlation output can be
    # re-keyed after a merge; without it, two rows would claim the same entity.
    key_map: dict[str, str] = field(default_factory=dict)


class MonitoringStore:
    """SQLite-backed history: windows, identity, scores, events, alerts."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(self.path))
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "MonitoringStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- windows -----------------------------------------------------------
    def register_window(
        self, label: str, start_ts: str, end_ts: str, path: str,
        n_tx: int, n_entities: int,
    ) -> int:
        """Index a batch. Re-processing the same label replaces its row rather
        than duplicating history, so a replay is idempotent."""
        cursor = self._connection.execute(
            """INSERT INTO windows (label, start_ts, end_ts, path, n_tx, n_entities)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(label) DO UPDATE SET
                   start_ts=excluded.start_ts, end_ts=excluded.end_ts,
                   path=excluded.path, n_tx=excluded.n_tx,
                   n_entities=excluded.n_entities""",
            (label, start_ts, end_ts, path, int(n_tx), int(n_entities)),
        )
        self._connection.commit()
        row = self._connection.execute(
            "SELECT window_id FROM windows WHERE label = ?", (label,)
        ).fetchone()
        return int(row["window_id"]) if row else int(cursor.lastrowid)

    def windows(self) -> list[WindowRecord]:
        rows = self._connection.execute(
            "SELECT * FROM windows ORDER BY window_id"
        ).fetchall()
        return [WindowRecord(**dict(row)) for row in rows]

    def last_window(self) -> WindowRecord | None:
        rows = self.windows()
        return rows[-1] if rows else None

    def previous_window(self) -> WindowRecord | None:
        rows = self.windows()
        return rows[-2] if len(rows) > 1 else None

    # ---- identity ----------------------------------------------------------
    def pinned_keys(self) -> dict[str, str]:
        return {
            row["address"]: row["entity_key"]
            for row in self._connection.execute(
                "SELECT address, entity_key FROM address_entity"
            )
        }

    def canonical(self, entity_key: str) -> str:
        """Resolve through any merges that happened after this key was minted."""
        seen: set[str] = set()
        key = entity_key
        while key not in seen:
            seen.add(key)
            row = self._connection.execute(
                "SELECT canonical_key FROM entity_alias WHERE alias_key = ?", (key,)
            ).fetchone()
            if row is None:
                return key
            key = row["canonical_key"]
        return key

    def first_window_of(self, entity_key: str) -> int:
        row = self._connection.execute(
            "SELECT MIN(first_window_id) AS first FROM address_entity WHERE entity_key = ?",
            (entity_key,),
        ).fetchone()
        if row and row["first"] is not None:
            return int(row["first"])
        return 1 << 30

    def resolve(
        self,
        address_to_entity: dict[str, str],
        window_id: int,
        stable_id_for_anchor: Any = None,
    ) -> Resolution:
        """Pin this window's clusters onto the registry.

        See the module docstring: derived keys are a starting point, pinned keys
        win, and a cluster containing addresses from two pinned entities is a
        merge -- which is a finding, not a bookkeeping problem.
        """
        from ml.cluster import stable_entity_id

        pinned = self.pinned_keys()

        # Group the window's clusters so each is decided once.
        clusters: dict[str, list[str]] = {}
        for address, derived in address_to_entity.items():
            clusters.setdefault(derived, []).append(address)

        resolved: dict[str, str] = {}
        key_map: dict[str, str] = {}
        new_entities: list[str] = []
        merges: list[MergeEvent] = []
        relabelled = 0
        absorbed_aliases: list[tuple[str, str]] = []

        for derived, addresses in clusters.items():
            existing = sorted({pinned[a] for a in addresses if a in pinned})

            if not existing:
                key = derived
                new_entities.append(key)
            else:
                # The survivor is the entity seen FIRST, tie-broken by key so the
                # choice is deterministic. Which operation absorbs which should
                # not depend on dictionary ordering.
                ordered = sorted(existing, key=lambda k: (self.first_window_of(k), k))
                key = ordered[0]
                if len(ordered) > 1:
                    merges.append(MergeEvent(survivor=key, absorbed=ordered[1:]))
                    absorbed_aliases.extend((alias, key) for alias in ordered[1:])
                if derived != key:
                    relabelled += 1

            key_map[derived] = key
            for address in addresses:
                address_to_entity[address] = key

        # Persist: addresses, aliases, survivor rows.
        self._connection.executemany(
            """INSERT INTO address_entity (address, entity_key, first_window_id)
               VALUES (?, ?, ?)
               ON CONFLICT(address) DO UPDATE SET entity_key=excluded.entity_key""",
            [(address, key, window_id) for address, key in address_to_entity.items()],
        )
        if absorbed_aliases:
            self._connection.executemany(
                """INSERT INTO entity_alias (alias_key, canonical_key, resolved_window)
                   VALUES (?, ?, ?)
                   ON CONFLICT(alias_key) DO UPDATE SET canonical_key=excluded.canonical_key""",
                [(alias, canonical, window_id) for alias, canonical in absorbed_aliases],
            )
        self._connection.commit()

        return Resolution(
            address_to_entity=address_to_entity,
            new_entities=new_entities,
            merges=merges,
            relabelled=relabelled,
            key_map=key_map,
        )

    def remap_derived(self, address_to_entity: dict[str, str]) -> dict[str, str]:
        """Map freshly-DERIVED entity keys onto canonical REGISTERED keys.

        A producer that re-derives entities from a window's file gets derived
        keys (hashes of the anchor address as this window saw it), while the
        store holds pinned, post-merge keys. The two agree only until an entity
        is relabelled or merged -- after which scores, alerts and history attach
        to node ids that do not exist, silently. That is exactly what happened
        to the payload builder, so the translation is explicit here rather than
        assumed anywhere.

        Returns `derived -> canonical` for every derived key with at least one
        registered address. Derived keys with no registered address are new
        entities and are simply absent from the map.
        """
        pinned = self.pinned_keys()
        members: dict[str, list[str]] = {}
        for address, derived in address_to_entity.items():
            members.setdefault(derived, []).append(address)

        mapping: dict[str, str] = {}
        for derived, addresses in members.items():
            known = sorted({
                self.canonical(pinned[address])
                for address in addresses if address in pinned
            })
            if known:
                # Deterministic choice. Merges are already resolved through
                # `canonical()`, so this is a single element in practice.
                mapping[derived] = known[0]
        return mapping

    # ---- entity state ------------------------------------------------------
    def record_entities(self, window_id: int, frame: pd.DataFrame) -> None:
        """Upsert the durable per-entity row.

        `first_window_id` is never overwritten -- it is the anchor of an entity's
        history, and rewriting it would silently redefine when an operation
        started.
        """
        rows = [
            (
                row.entity_id, window_id, window_id,
                int(getattr(row, "address_count", 0)),
                int(row.risk), row.band,
                getattr(row, "role", None),
                int(getattr(row, "community_id", -1)),
            )
            for row in frame.itertuples(index=False)
        ]
        self._connection.executemany(
            """INSERT INTO entities (entity_key, first_window_id, last_window_id,
                                     address_count, last_risk, last_band, role, community_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(entity_key) DO UPDATE SET
                   last_window_id = excluded.last_window_id,
                   address_count  = excluded.address_count,
                   last_risk      = excluded.last_risk,
                   last_band      = excluded.last_band,
                   role           = excluded.role,
                   community_id   = excluded.community_id""",
            rows,
        )
        self._connection.commit()

    def known_entity_keys(self) -> set[str]:
        """Every key ever seen, canonicalised through merges."""
        keys = {
            row["entity_key"]
            for row in self._connection.execute("SELECT DISTINCT entity_key FROM address_entity")
        }
        return {self.canonical(key) for key in keys}

    def latest_window_for(self, entity_key: str) -> int | None:
        """Most recent window this entity was scored in, or None.

        A lead exists across windows, so the dossier must find it wherever it
        last appeared rather than assuming the newest window -- otherwise asking
        for a week-old lead 404s at the moment an analyst needs it.
        """
        row = self._connection.execute(
            "SELECT MAX(window_id) AS latest FROM scores WHERE entity_key = ?",
            (entity_key,),
        ).fetchone()
        return int(row["latest"]) if row and row["latest"] is not None else None

    def entities_before(self, window_id: int) -> set[str]:
        """Every entity seen in any window strictly before this one."""
        rows = self._connection.execute(
            "SELECT DISTINCT entity_key FROM scores WHERE window_id < ?", (window_id,)
        ).fetchall()
        return {self.canonical(row["entity_key"]) for row in rows}

    # ---- scores -----------------------------------------------------------
    def record_scores(self, window_id: int, frame: pd.DataFrame) -> None:
        """Persist one window's predictions and the features behind them.

        Only FEATURE_COLUMNS are serialised. Storing the whole frame would drag
        in presentation columns like `role` (a string) and `community_id` (an
        identifier, not a quantity), and a feature vector is what the delta
        attribution needs.
        """
        from ml.features import FEATURE_COLUMNS

        rows: list[tuple[Any, ...]] = []
        for row in frame.itertuples(index=False):
            features = {
                name: float(getattr(row, name))
                for name in FEATURE_COLUMNS
                if hasattr(row, name)
            }
            rows.append((
                row.entity_id, window_id, int(row.risk),
                float(getattr(row, "anomaly", 0.0)), row.band,
                json.dumps(features),
            ))
        self._connection.executemany(
            """INSERT INTO scores (entity_key, window_id, risk, anomaly, band, features)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(entity_key, window_id) DO UPDATE SET
                   risk=excluded.risk, anomaly=excluded.anomaly,
                   band=excluded.band, features=excluded.features""",
            rows,
        )
        self._connection.commit()

    def scores(self, window_id: int | None = None) -> pd.DataFrame:
        if window_id is None:
            query, params = (
                "SELECT s.*, w.label FROM scores s JOIN windows w USING(window_id) "
                "ORDER BY window_id", (),
            )
        else:
            query, params = "SELECT * FROM scores WHERE window_id = ?", (window_id,)
        return pd.read_sql_query(query, self._connection, params=params)

    def feature_matrix(self, window_id: int) -> pd.DataFrame:
        """One window's stored features, as a DataFrame indexed by entity."""
        frame = self.scores(window_id)
        if frame.empty:
            return pd.DataFrame()
        features = pd.DataFrame(
            [json.loads(value) for value in frame["features"]],
            index=frame["entity_key"],
        )
        return features

    def features_at_peak(self) -> pd.DataFrame:
        """Per entity, the feature vector from the batch in which it scored highest.

        Needed to explain a whole-capture view. In that view an entity's risk is
        the PEAK it reached in some batch, so explaining it with whole-capture
        features produces bars that reconcile to a different number than the one
        on screen -- an explanation that does not explain the figure beside it,
        which is worse than showing no bars at all.

        Read from the stored vectors rather than recomputed, so the explanation
        describes exactly the scoring run that produced the peak.
        """
        statement = """
            SELECT s.entity_key AS entity_key, s.features AS features
            FROM scores s
            JOIN (SELECT entity_key, MAX(risk) AS peak FROM scores GROUP BY entity_key) p
              ON s.entity_key = p.entity_key AND s.risk = p.peak
            GROUP BY s.entity_key
        """
        rows = self._connection.execute(statement).fetchall()
        if not rows:
            return pd.DataFrame()

        records = []
        for row in rows:
            vector = json.loads(row["features"])
            vector["entity_key"] = row["entity_key"]
            records.append(vector)
        return pd.DataFrame(records).set_index("entity_key")

    # ---- events and alerts ------------------------------------------------
    def record_events(self, events: Iterable[dict[str, Any]]) -> int:
        rows = [
            (event["window_id"], event["entity_key"], event["type"],
             event["severity"], json.dumps(event.get("detail", {})))
            for event in events
        ]
        if not rows:
            return 0
        self._connection.executemany(
            """INSERT INTO events (window_id, entity_key, type, severity, detail)
               VALUES (?, ?, ?, ?, ?)""",
            rows,
        )
        self._connection.commit()
        return len(rows)

    def events(self, window_id: int | None = None) -> pd.DataFrame:
        if window_id is None:
            query, params = (
                "SELECT e.*, w.label FROM events e JOIN windows w USING(window_id) "
                "ORDER BY window_id, event_id", (),
            )
        else:
            query, params = (
                "SELECT * FROM events WHERE window_id = ? ORDER BY event_id", (window_id,),
            )
        frame = pd.read_sql_query(query, self._connection, params=params)
        if not frame.empty:
            frame["detail"] = frame["detail"].map(json.loads)
        return frame

    def upsert_alert(
        self, entity_key: str, window_id: int, risk: int, status: str = "new",
    ) -> None:
        """One row per entity, updated in place: an alert with a memory."""
        self._connection.execute(
            """INSERT INTO alerts (entity_key, first_window, last_window,
                                   peak_risk, current_risk, status)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(entity_key) DO UPDATE SET
                   last_window  = excluded.last_window,
                   peak_risk    = MAX(alerts.peak_risk, excluded.peak_risk),
                   current_risk = excluded.current_risk,
                   status       = CASE WHEN alerts.status IN
                                       ('closed_false_positive','closed_escalated')
                                       THEN excluded.status ELSE alerts.status END""",
            (entity_key, window_id, window_id, int(risk), int(risk), status),
        )
        self._connection.commit()

    def set_alert_status(self, entity_key: str, status: str, assignee: str | None = None,
                         note: str | None = None) -> None:
        """The analyst's decision, remembered. This is what makes it a tool
        rather than a report."""
        if status not in ALERT_STATUSES:
            raise ValueError(f"unknown status '{status}' -- expected one of {ALERT_STATUSES}")
        self._connection.execute(
            "UPDATE alerts SET status = ?, assignee = COALESCE(?, assignee), "
            "note = COALESCE(?, note) WHERE entity_key = ?",
            (status, assignee, note, entity_key),
        )
        self._connection.commit()

    def alerts(self, status: str | None = None) -> pd.DataFrame:
        query = "SELECT * FROM alerts"
        params: tuple[Any, ...] = ()
        if status:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY current_risk DESC"
        return pd.read_sql_query(query, self._connection, params=params)

    def summary(self) -> dict[str, Any]:
        def scalar(sql: str) -> int:
            row = self._connection.execute(sql).fetchone()
            return int(row[0]) if row and row[0] is not None else 0

        # `open_alerts` counts DISTINCT CURRENT identities, not alert rows.
        #
        # An alert raised on day 3 for a group that a later batch merged into
        # another group stays in the table as a historical record, and its key no
        # longer names a group of its own. Counting rows reported 88 open leads
        # where the payload reported 85 flagged wallet groups -- and the two
        # numbers appeared next to each other on the cover. Both were right about
        # different questions, which is the worst kind of wrong: an unexplained
        # discrepancy in the one place a reader is checking whether we are honest.
        #
        # `entity_alias` is the store's own record of which key became which, so
        # the resolution happens here rather than in the interface.
        return {
            "windows": scalar("SELECT COUNT(*) FROM windows"),
            "addresses": scalar("SELECT COUNT(*) FROM address_entity"),
            "entities": scalar("SELECT COUNT(DISTINCT entity_key) FROM address_entity"),
            "merged_entities": scalar("SELECT COUNT(*) FROM entity_alias"),
            "score_rows": scalar("SELECT COUNT(*) FROM scores"),
            "events": scalar("SELECT COUNT(*) FROM events"),
            "alerts": scalar("SELECT COUNT(*) FROM alerts"),
            "open_alerts": scalar(
                "SELECT COUNT(DISTINCT COALESCE("
                "  (SELECT a.canonical_key FROM entity_alias a "
                "   WHERE a.alias_key = alerts.entity_key),"
                "  alerts.entity_key)) "
                "FROM alerts WHERE status NOT LIKE 'closed%'"
            ),
            # Kept separately so the difference is inspectable rather than lost.
            "open_alert_rows": scalar(
                "SELECT COUNT(*) FROM alerts WHERE status NOT LIKE 'closed%'"
            ),
        }

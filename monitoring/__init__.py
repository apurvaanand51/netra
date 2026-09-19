"""
Monitoring -- state, windows, events and alert lifecycle.

The Analysis half of "AI-Powered Monitoring & Analysis of Bitcoin Transaction
Traffic" is `ingestion/`, `correlation/`, `ml/`. This package is the Monitoring
half: memory across runs, what changed since last time, and what an analyst
should do about it.

    store.py     SQLite history + address->entity identity pinning (the prerequisite)
    events.py    deltas between windows, turned into typed events with attribution
    pipeline.py  the windowed run: trailing-window features -> score -> diff -> persist
"""

from monitoring.store import ALERT_STATUSES, MonitoringStore, Resolution, WindowRecord

__all__ = ["ALERT_STATUSES", "MonitoringStore", "Resolution", "WindowRecord"]

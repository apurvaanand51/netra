"""
NETRA backend -- FastAPI application.

    main.py    the app: API endpoints, static dashboard, job control
    jobs.py    background job registry (long analyses must not block a request)
    report.py  printable case dossier for a single lead

Deliberately no imports here. `__init__` is executed by any `import backend`,
and pulling the whole application (and its SQLite handle and job registry) into
that is both slower and a needless import cycle. Import `backend.main` directly.
"""

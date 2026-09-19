netra/
├─ README.md                       judge-facing: architecture + one-command run
├─ LICENSE
├─ .gitignore                      decides what never gets committed
├─ .gitattributes                  line-ending rules  (step 2)
├─ .dockerignore
├─ requirements.txt                pinned = reproducible
├─ Makefile                        Linux / CI targets
├─ tasks.py                        cross-platform runner: gen|train|analyze|run|smoke|test
├─ pipeline_run.py                 orchestrator: raw file in → results.json out
├─ dataset_export.py               builds NETRA_Ingestion_Dataset.xlsx
├─ model_report.py                 builds NETRA_Model_Performance.xlsx
├─ Dockerfile
├─ docker-compose.yml
├─ run.sh                          one-command offline start (Linux/macOS)
├─ run.bat                         one-command offline start (Windows)
├─ .github/
│  └─ workflows/
│     ├─ ci.yml                    install + smoke-test every push
│     └─ release.yml               tagged release → air-gapped bundle
├─ schemas/
│  ├─ README.md
│  └─ results.schema.json          THE FROZEN CONTRACT
├─ generator/
│  ├─ __init__.py
│  └─ generate.py                  synthetic data + planted ground truth
├─ ingestion/
│  ├─ __init__.py
│  ├─ load.py
│  └─ normalize.py                 CSV/JSON/XML → validated records
├─ correlation/
│  ├─ __init__.py
│  └─ engine.py                    network ⇄ blockchain fusion
├─ ml/
│  ├─ __init__.py
│  ├─ cluster.py                   common-input → connected components
│  ├─ anomaly.py                   IsolationForest        (model #1)
│  ├─ patterns.py                  peel / mixer / collector detectors
│  ├─ features.py                  24 per-entity features
│  ├─ risk.py                      RandomForest           (model #2)
│  ├─ train.py
│  └─ evaluate.py                  P/R/F1/AUC/ARI against ground truth
├─ backend/
│  ├─ __init__.py
│  ├─ main.py                      FastAPI app, 13 endpoints
│  ├─ jobs.py                      background job queue
│  └─ report.py                    printable case dossier
├─ frontend/
│  ├─ netra.html
│  ├─ app.js                       adapter: contract → DOM, no analysis logic
│  ├─ build.py
│  └─ vendor/                      COMMITTED on purpose (offline operation)
│     ├─ vis-network.min.js
│     ├─ chart.umd.min.js
│     ├─ fonts.css
│     └─ fonts/                    42 files
├─ models/                         trained artifacts — travel with the repo
│  ├─ .gitkeep
│  ├─ risk.joblib
│  ├─ anomaly.joblib
│  ├─ feature_columns.json
│  └─ metrics.json
├─ docs/
│  ├─ README.md
│  └─ LEARNING_GUIDE.md            16 sections, beginner-level
├─ tests/
│  ├─ __init__.py
│  ├─ test_smoke.py
│  ├─ api_smoke.py
│  ├─ validate_contract.py
│  └─ fixtures/
│     └─ sample_results.json
├─ data/                           GENERATED — only .gitkeep is committed
│  └─ .gitkeep
├─ notebooks/                      Colab retrain (step 6)
│  └─ NETRA_Colab_Retrain.ipynb
├─ out/                            GENERATED — ignored (results.json)
└─ uploads/                        GENERATED — ignored (user uploads)
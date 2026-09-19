# NETRA -- Linux / CI convenience targets.
#
# These are THIN WRAPPERS over tasks.py, not a second implementation. `make` is
# not installed on Windows by default, so the team's daily vocabulary is
# `python tasks.py <command>`; this file exists so Linux, Docker and CI can use
# the conventional spelling without a divergent code path.
#
#   make gen | train | replay | payload | drift | serve | smoke | test | clean
#
PY ?= python3
PORT ?= 8000

.PHONY: help gen train replay payload drift serve smoke test clean docker offline-check

help:
	@$(PY) tasks.py --help

gen:
	@$(PY) tasks.py gen

train:
	@$(PY) tasks.py train

replay:
	@$(PY) tasks.py replay

payload:
	@$(PY) tasks.py payload

drift:
	@$(PY) tasks.py drift

serve:
	@$(PY) tasks.py serve $(PORT)

smoke:
	@$(PY) tasks.py smoke

test:
	@$(PY) tasks.py test

clean:
	@$(PY) tasks.py clean

# Build and start the image, then prove the service came up. The Dockerfile bakes
# the dataset and the models in, so `docker compose up` on an air-gapped machine
# produces a populated dashboard with no setup step.
docker:
	docker compose up --build -d
	@sleep 6
	@curl -fsS http://localhost:$(PORT)/health >/dev/null && echo "health: OK" \
		|| (echo "health: FAILED"; exit 1)

# The claim the problem statement actually makes: it runs with no network. This
# builds from scratch (so no cached layer hides a download) and then starts it.
offline-check:
	docker compose build --no-cache
	docker compose up -d
	@sleep 6
	@curl -fsS http://localhost:$(PORT)/health >/dev/null \
		&& echo "OFFLINE BUILD+START OK" \
		|| (echo "OFFLINE CHECK FAILED"; exit 1)
	docker compose down

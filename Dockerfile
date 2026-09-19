# NETRA -- offline image.
#
# WHY 3.10-slim
# -------------
# The pipeline is verified on Python 3.10 and the trained artifacts are pickled
# by that version's library builds. A different minor version means a different
# libstdc++/BLAS underneath numpy and scikit-learn, and a `.joblib` that loads
# here can fail there with no obvious cause. The image matches the environment the
# numbers were measured in, which removes a whole class of "works on my machine".
#
# WHY THE LAYER ORDER MATTERS
# ---------------------------
# Docker caches each instruction. Requirements go before the source so that
# editing a `.py` file rebuilds in seconds instead of reinstalling scipy -- which
# matters when the network is the thing you do not have.
#
# WHY DATA AND MODELS ARE BAKED IN
# --------------------------------
# The problem statement requires an air-gapped Linux deployment. Running the
# generator and the training inside the build means `docker run` on an isolated
# host produces a fully populated dashboard with no setup step and no network.
# It also means the shipped tool and the reported metrics cannot drift apart: the
# scorecard travels inside the image next to the model that produced it.
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# ---- dependencies (separate layer, cached) --------------------------------
COPY requirements.txt ./
# `wheels/` ships empty in git (see .gitignore) so this COPY always has a source.
# Populate it with `pip download -r requirements.txt -d wheels/` on a connected
# machine and the build installs offline with no registry access at all.
COPY wheels/ ./wheels/
RUN if [ -n "$(ls -A wheels 2>/dev/null)" ]; then \
        echo "installing from the vendored offline wheel cache"; \
        pip install --no-index --find-links=wheels/ -r requirements.txt; \
    else \
        echo "no wheel cache present; installing from the index"; \
        pip install -r requirements.txt; \
    fi

# ---- the rest of the project ---------------------------------------------
COPY . .

# ---- bake the dataset, the models and the history ------------------------
# One RUN so the three steps share a layer. Each is reproducible from the pinned
# seed, so the image is deterministic rather than merely archived.
RUN python tasks.py gen \
 && python tasks.py train \
 && python tasks.py replay

# ---- run as a non-root user ----------------------------------------------
# A tool that reads seized evidence should not be running as root on the host
# that holds it. Cheap to arrange at build time, awkward to retrofit later.
RUN useradd --create-home --uid 10001 netra \
 && chown -R netra:netra /app
USER netra

EXPOSE 8000

# A healthcheck distinguishes "the container is running" from "the tool works".
# Those are different things: a process can be alive and serving 500s.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# One process serves the API and the dashboard, so deployment is one command and
# there is no CORS to configure and no reverse proxy to misconfigure.
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

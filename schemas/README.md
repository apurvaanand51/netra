# The NETRA contract

## What this folder is

`results.schema.json` is **the frozen contract** — the single handshake between the three squads:

```
Forge (data + correlation)  ─┐
Brain (ML)                  ─┼──►  results.json  ──►  Netra (API + dashboard)
Netra (platform)            ─┘        (this shape)
```

Nobody invents their own field names. Nobody adds a field quietly. If the shape changes, the **Captain** announces it, and everyone rebases.

## Why we freeze it first (the single most important teamwork decision)

The number one way a six-person hackathon team fails is not bad code — it's **components that don't fit together until hour 30**, when there's no time left to fix them.

Freezing the contract before anyone writes real logic buys us three things:

1. **Parallelism.** All three squads build at the same time instead of waiting on each other.
2. **A stub is enough.** The platform squad can build the API and wire the whole dashboard against `tests/fixtures/sample_results.json` while the ML squad is still training. The UI doesn't care whether the JSON came from a real model or a text file.
3. **Automated enforcement.** `jsonschema` turns the contract into a test. If someone's output drifts, the build goes red immediately — not at 3am on demo day.

## How to validate

```bash
python -m tests.validate_contract out/results.json
```

This is also step 3 of `python tasks.py smoke`.

## The shape at a glance

| Key | What it carries | Who consumes it |
|---|---|---|
| `meta` | record/entity counts, timing | dashboard header ("48,213 records parsed") |
| `entities` | every subject: wallet clusters **and** IP endpoints | graph nodes, alert targets, evidence panel |
| `edges` | `kind: "flow"` = on-chain transfer, `kind: "control"` = IP controlled a wallet | graph edges (solid vs dashed) |
| `alerts` | ranked investigative leads | the alert rail — *the product* |
| `clusters` | entity groupings + method | cluster colouring, ARI evaluation |
| `series` | hourly BTC volume + risk-band counts | the two dashboard charts |
| `geo_breakdown` | activity share per country | the geo panel |
| `metrics` | precision / recall / F1 / AUC / ARI vs planted ground truth | the "prove it's real AI" moment |

## Design rules the schema encodes

- **`entities` is unified.** Wallet clusters and IP addresses are both entities; `kind` distinguishes them. This keeps the graph builder trivial and matches how an analyst thinks (an IP endpoint *is* a subject of interest).
- **`edges` carries semantics, not styling.** `kind` says what the relationship *is*; the frontend decides that flow = solid and control = dashed. Analysis stays in the backend, presentation stays in the frontend.
- **`metrics` allows `null`.** A missing metric means "not yet measured". It does **not** mean "put a placeholder number here". Never fake a number in this block — it is the single most judge-scrutinised part of the payload, and your credibility rests on it.
- **`reasons` uses a small closed vocabulary** (`flow`, `exch`, `time`, `clus`) so the UI can map each reason to an icon and colour without guessing.

## ⚠️ About `tests/fixtures/sample_results.json`

That file is a **development fixture**, not a result. Its metric values are illustrative, chosen to match the dashboard's target look. It exists so the platform squad can build the entire UI before the ML exists.

It must never be presented as a real analysis run, and the pipeline must never silently fall back to it. The real numbers come from `python tasks.py train` against planted ground truth.

"""
Contract validation -- turns schemas/results.schema.json into an executable test.

This is what makes the frozen contract real. Without it, the schema is just a
document people drift away from. With it, drift fails the build immediately.

Usage:
    python -m tests.validate_contract out/results.json
    python -m tests.validate_contract --fixture        # validate the dev fixture
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schemas" / "results.schema.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "sample_results.json"


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_document(doc: dict, schema: dict | None = None) -> list[str]:
    """Return a list of human-readable problems. Empty list means valid."""
    schema = schema or load_schema()
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    problems: list[str] = []
    for error in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        location = "/".join(str(p) for p in error.absolute_path) or "<root>"
        problems.append(f"{location}: {error.message}")
    return problems


def validate_file(path: Path) -> list[str]:
    if not path.exists():
        return [f"file not found: {path}"]
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"not valid JSON: {exc}"]
    return validate_document(doc)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    target = FIXTURE_PATH if argv[0] == "--fixture" else Path(argv[0])
    problems = validate_file(target)

    if problems:
        print(f"CONTRACT VIOLATION in {target.name} -- {len(problems)} problem(s):\n")
        for problem in problems:
            print(f"  - {problem}")
        print(
            "\nThe payload does not match schemas/results.schema.json.\n"
            "Fix the producer, or ask the Captain to amend the contract."
        )
        return 1

    print(f"OK  {target.name} satisfies the NETRA contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

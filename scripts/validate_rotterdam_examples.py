#!/usr/bin/env python3
"""Validate nbot_lite tariff calculations against Rotterdam 2026 PDF examples."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from PyPDF2 import PdfReader


def repo_root() -> Path:
    """Return the repository root for this script."""
    return Path(__file__).resolve().parents[3]


def read_json(path: Path) -> dict:
    """Load JSON from disk."""
    return json.loads(path.read_text())


def assert_pdf_examples(pdf_path: Path) -> None:
    """Check the uploaded Rotterdam PDF contains the published example totals."""
    reader = PdfReader(str(pdf_path))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    required = [
        "Example 1",
        "€26,216.63",
        "Example 2",
        "€1,304.75",
        "Example 3",
        "€28,179.63",
        "Example 4",
        "€21,808.74",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        raise SystemExit(f"Rotterdam PDF example text not found: {missing}")


def run_core(core: Path, rule_pack: Path, vessel: dict) -> dict:
    """Run the C++ core with one generated rule pack and vessel payload."""
    payload = {"vessel": vessel, "rule_pack": read_json(rule_pack)}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as temp:
        json.dump(payload, temp)
        input_path = Path(temp.name)
    try:
        completed = subprocess.run(
            [
                str(core),
                "--mode",
                "calculate",
                "--rules",
                str(rule_pack),
                "--fixture",
                str(repo_root() / "poc/port_tariff_agent/data/empty_vessel.template.json"),
                "--providers",
                str(repo_root() / "poc/port_tariff_agent/data/model_providers.example.json"),
                "--input",
                str(input_path),
            ],
            check=False,
            text=True,
            capture_output=True,
        )
    finally:
        input_path.unlink(missing_ok=True)
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.strip() or completed.stdout.strip())
    return json.loads(completed.stdout)


def main() -> None:
    """Validate all Annex 2 seaport examples."""
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--core", type=Path, default=repo_root() / "build_res/port_tariff_core")
    parser.add_argument(
        "--rules",
        type=Path,
        default=repo_root() / "poc/port_tariff_agent/tests/fixtures/rotterdam_2026_annex2_examples.rule_pack.json",
    )
    parser.add_argument(
        "--vessels",
        type=Path,
        default=repo_root() / "poc/port_tariff_agent/tests/fixtures/rotterdam_2026_annex2_examples.vessels.json",
    )
    args = parser.parse_args()

    assert_pdf_examples(args.pdf)
    cases = read_json(args.vessels)
    for case_id, case in cases.items():
        result = run_core(args.core, args.rules, case["vessel"])
        actual = round(float(result["total"]), 2)
        expected = round(float(case["expected_total"]), 2)
        if actual != expected:
            raise SystemExit(f"{case_id}: expected {expected}, got {actual}")
        print(f"{case_id}: OK {actual:.2f}")
    print("Rotterdam 2026 Annex 2 examples validated.")


if __name__ == "__main__":
    main()

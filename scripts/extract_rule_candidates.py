#!/usr/bin/env python3
"""Extract rough tariff-rule candidates from a PDF/text document.

This is intentionally a satellite-style helper, not business logic. It turns a new
document into evidence-bearing snippets that a model adapter can normalize into
`port_tariff.rule_pack.v1`, then the C++ core evaluates that rule pack.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


TERMS = [
    "light dues",
    "port dues",
    "pilotage",
    "towage",
    "tugs",
    "vessel traffic services",
    "vts",
    "running of vessel lines",
    "berthing services",
    "cargo dues",
]


def read_document(path: Path) -> list[dict]:
    if path.suffix.lower() == ".pdf":
        from PyPDF2 import PdfReader

        reader = PdfReader(str(path))
        return [
            {"page": index + 1, "text": page.extract_text() or ""}
            for index, page in enumerate(reader.pages)
        ]
    return [{"page": 1, "text": path.read_text(errors="ignore")}]


def window(text: str, term: str, radius: int = 900) -> str:
    match = re.search(re.escape(term), text, flags=re.IGNORECASE)
    if not match:
        return ""
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("document", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    pages = read_document(args.document)
    candidates = []
    for page in pages:
        text = page["text"]
        for term in TERMS:
            snippet = window(text, term)
            if snippet:
                candidates.append(
                    {
                        "term": term,
                        "page": page["page"],
                        "snippet": snippet,
                        "normalize_instruction": "Extract applicability, charge basis, unit, formula, rates, minimums, surcharges, exemptions, and evidence into port_tariff.rule_pack.v1.",
                    }
                )

    payload = {
        "schema_version": "port_tariff.candidate_rules.v1",
        "document": str(args.document),
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    if args.out:
        args.out.write_text(json.dumps(payload, indent=2))
    else:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

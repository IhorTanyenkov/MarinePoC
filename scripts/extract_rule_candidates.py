#!/usr/bin/env python3
"""Extract rough tariff-rule candidates from a PDF/text document.

Dev helper, not the runtime path. Pulls candidate keyphrases out of a fresh
tariff document so a human or model can sanity-check what an extraction agent
will see. Uses the same data-driven `DocumentTools` the API path uses, so the
output is consistent across all ports — no hardcoded jurisdiction-specific
charge family names.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from port_tariff_agent.tools.document_tools import DocumentTools  # noqa: E402


def read_document(path: Path) -> list[dict]:
    """Read a PDF or text file into the {page, text} shape DocumentTools expects."""
    if path.suffix.lower() == ".pdf":
        from PyPDF2 import PdfReader

        reader = PdfReader(str(path))
        return [
            {"page": index + 1, "text": page.extract_text() or ""}
            for index, page in enumerate(reader.pages)
        ]
    return [{"page": 1, "text": path.read_text(errors="ignore")}]


def window_around(text: str, term: str, radius: int = 900) -> str:
    """Return a single-line excerpt centered on the first occurrence of `term`."""
    match = re.search(re.escape(term), text, flags=re.IGNORECASE)
    if not match:
        return ""
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--limit", type=int, default=18, help="Max keyphrases to emit")
    args = parser.parse_args()

    pages = read_document(args.document)
    tools = DocumentTools(ROOT / ".runtime")
    keyphrases = tools._document_keyphrases(pages, limit=args.limit)

    candidates: list[dict] = []
    for term, score in keyphrases:
        for page in pages:
            snippet = window_around(page["text"], term)
            if snippet:
                candidates.append({
                    "term": term,
                    "score": round(score, 3),
                    "page": page["page"],
                    "snippet": snippet,
                    "normalize_instruction": "Extract applicability, charge basis, unit, formula, rates, minimums, surcharges, exemptions, and evidence into port_tariff.rule_pack.v1.",
                })
                break

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

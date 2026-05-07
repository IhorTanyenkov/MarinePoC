#!/usr/bin/env python3
"""Render docs/USER_FLOW_AND_ARCHITECTURE.md into a styled PDF via WeasyPrint.

Mermaid blocks are replaced with formatted diagram cards so the output is
self-contained without requiring a browser or network access.
"""

from __future__ import annotations

import re
from pathlib import Path

import markdown
from weasyprint import HTML, CSS

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "USER_FLOW_AND_ARCHITECTURE.md"
OUT = ROOT / "docs" / "Port_Tariff_Agent_Architecture.pdf"


CSS_STYLE = """
@page {
  size: A4;
  margin: 24mm 22mm 24mm 22mm;
  @bottom-right {
    content: "p. " counter(page) " of " counter(pages);
    font-family: "Inter", "Helvetica Neue", Helvetica, sans-serif;
    font-size: 8.5pt;
    color: #62696f;
  }
  @bottom-left {
    content: "Port Tariff Agent · User Flow & Architecture";
    font-family: "Inter", "Helvetica Neue", Helvetica, sans-serif;
    font-size: 8.5pt;
    color: #62696f;
  }
}

* { box-sizing: border-box; }

html, body {
  font-family: "Inter", "Helvetica Neue", Helvetica, "Segoe UI", system-ui, sans-serif;
  font-size: 10.4pt;
  line-height: 1.55;
  color: #0c0e10;
}

h1 {
  font-size: 24pt;
  font-weight: 700;
  letter-spacing: -0.015em;
  margin: 0 0 12pt;
  color: #0c0e10;
  border-bottom: 2px solid #0f766e;
  padding-bottom: 6pt;
}

h2 {
  font-size: 15pt;
  font-weight: 650;
  letter-spacing: -0.01em;
  margin: 20pt 0 8pt;
  color: #0c0e10;
  page-break-after: avoid;
}

h3 {
  font-size: 12.5pt;
  font-weight: 650;
  margin: 14pt 0 6pt;
  color: #0c0e10;
  page-break-after: avoid;
}

p { margin: 0 0 8pt; }

ul, ol { margin: 0 0 8pt; padding-left: 22pt; }
li { margin-bottom: 3pt; }

a { color: #0f766e; text-decoration: none; }

code {
  font-family: "SFMono-Regular", "Menlo", "Consolas", monospace;
  font-size: 9.4pt;
  background: #f1f3f5;
  padding: 1pt 5pt;
  border-radius: 3pt;
  color: #064e44;
}

pre {
  font-family: "SFMono-Regular", "Menlo", "Consolas", monospace;
  font-size: 8.8pt;
  background: #0c0e10;
  color: #d4d8db;
  padding: 10pt 12pt;
  border-radius: 6pt;
  overflow-x: auto;
  line-height: 1.45;
  white-space: pre;
  margin: 8pt 0;
  page-break-inside: avoid;
}

pre code {
  background: transparent;
  color: inherit;
  font-size: inherit;
  padding: 0;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 9.5pt;
  margin: 8pt 0;
  page-break-inside: avoid;
}

th, td {
  text-align: left;
  padding: 6pt 8pt;
  border-bottom: 1px solid #e6e8eb;
  vertical-align: top;
}

th {
  font-weight: 650;
  background: #fafbfc;
  border-bottom: 2px solid #d2d6da;
  color: #0c0e10;
}

td:last-child, th:last-child {
  text-align: left;
}

table.numeric td:nth-last-child(1),
table.numeric th:nth-last-child(1) {
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-family: "SFMono-Regular", "Menlo", "Consolas", monospace;
}

blockquote {
  margin: 8pt 0;
  padding: 10pt 14pt;
  border-left: 3pt solid #0f766e;
  background: #ccfbf1;
  color: #064e44;
  border-radius: 0 4pt 4pt 0;
}

blockquote p { margin: 0; }

strong { font-weight: 650; }

hr {
  border: 0;
  border-top: 1px solid #e6e8eb;
  margin: 18pt 0;
}

.cover {
  padding: 80pt 0 40pt;
  page-break-after: always;
}

.cover-eyebrow {
  font-size: 9pt;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: #0f766e;
  font-weight: 700;
  margin-bottom: 18pt;
}

.cover h1 {
  font-size: 32pt;
  border-bottom: none;
  padding-bottom: 0;
  letter-spacing: -0.02em;
  margin-bottom: 16pt;
  line-height: 1.05;
}

.cover-summary {
  font-size: 12pt;
  color: #2a2f33;
  line-height: 1.55;
  max-width: 130mm;
}

.cover-meta {
  margin-top: 60pt;
  font-size: 9.5pt;
  color: #62696f;
  border-top: 1px solid #e6e8eb;
  padding-top: 14pt;
}

.cover-meta dl {
  display: grid;
  grid-template-columns: 30mm 1fr;
  row-gap: 6pt;
  margin: 0;
}

.cover-meta dt {
  font-weight: 650;
  color: #0c0e10;
}

.cover-meta dd { margin: 0; }

.diagram {
  border: 1px solid #d2d6da;
  border-radius: 6pt;
  background: #fafbfc;
  padding: 12pt 14pt;
  margin: 10pt 0;
  page-break-inside: avoid;
}

.diagram .diagram-label {
  font-size: 8.5pt;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  font-weight: 700;
  color: #62696f;
  margin-bottom: 8pt;
}

.diagram pre {
  background: transparent;
  color: #0c0e10;
  border-radius: 0;
  padding: 0;
  font-size: 9pt;
  line-height: 1.5;
  border: 0;
  margin: 0;
}

.proof-card {
  border: 2px solid #0f766e;
  background: #ccfbf1;
  border-radius: 8pt;
  padding: 14pt 18pt;
  margin: 12pt 0 14pt;
  page-break-inside: avoid;
}

.proof-card h2 {
  margin-top: 0;
  color: #064e44;
}

.proof-card table th { background: rgba(255,255,255,0.6); }

.toc {
  page-break-after: always;
  padding-top: 8pt;
}

.toc h2 {
  margin-top: 0;
  border-bottom: 2px solid #e6e8eb;
  padding-bottom: 6pt;
}

.toc ol {
  list-style: none;
  padding-left: 0;
  font-size: 11pt;
  line-height: 1.85;
}

.toc ol li::before {
  content: counter(toc-counter, decimal-leading-zero) "  ";
  font-family: "SFMono-Regular", monospace;
  color: #0f766e;
  font-weight: 650;
  counter-increment: toc-counter;
}

.toc ol { counter-reset: toc-counter; }
"""


def replace_mermaid_blocks(md_text: str) -> str:
    """Wrap fenced ```mermaid blocks in a labeled <div class='diagram'> for visual clarity."""

    def repl(match: re.Match) -> str:
        body = match.group(1).strip()
        escaped = (
            body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        return (
            "<div class=\"diagram\"><div class=\"diagram-label\">Diagram</div>"
            f"<pre>{escaped}</pre></div>"
        )

    return re.sub(r"```mermaid\n(.*?)\n```", repl, md_text, flags=re.DOTALL)


def build_html(md_text: str) -> str:
    md_text = replace_mermaid_blocks(md_text)

    md = markdown.Markdown(
        extensions=[
            "extra",
            "tables",
            "sane_lists",
            "fenced_code",
        ]
    )
    body = md.convert(md_text)

    cover = (
        "<section class=\"cover\">"
        "<p class=\"cover-eyebrow\">NBot Port Tariff Agent · PoC</p>"
        "<h1>Generalisable Port Tariff Calculator — User Flow &amp; Architecture</h1>"
        "<p class=\"cover-summary\">Upload any port tariff PDF; an LLM agent reads it natively, "
        "extracts the rate logic into a portable rule pack, validates the pack against worked "
        "examples found inside the document, and exposes a deterministic calculator tool. "
        "Vessel facts in → totals + evidence + execution trace out.</p>"
        "<div class=\"cover-meta\">"
        "<dl>"
        "<dt>Author</dt><dd>Ihor Tanyenkov</dd>"
        "<dt>Validated on</dt><dd>Port of Rotterdam — Port Tariffs 2026 (Annex 2 Example 4)</dd>"
        "<dt>Stack</dt><dd>FastAPI · React · C++ deterministic core · Gemini / Claude / OpenAI-compatible</dd>"
        "</dl>"
        "</div>"
        "</section>"
    )

    body = body.replace("<table>", "<table class=\"numeric\">", 1)

    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        "<title>Port Tariff Agent — Architecture</title>"
        "</head><body>"
        + cover
        + body
        + "</body></html>"
    )


def main() -> None:
    md_text = SRC.read_text(encoding="utf-8")
    html = build_html(md_text)
    HTML(string=html, base_url=str(SRC.parent)).write_pdf(
        target=str(OUT),
        stylesheets=[CSS(string=CSS_STYLE)],
    )
    size_kb = OUT.stat().st_size / 1024
    print(f"Wrote {OUT} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()

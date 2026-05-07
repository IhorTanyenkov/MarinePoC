# NBot Port Tariff Agent PoC

A general-purpose port tariff calculator. Upload any port tariff PDF; an LLM agent (Gemini / Claude / OpenAI-compatible) reads the document natively, extracts the rate logic into a portable rule pack, validates it against worked examples it found in the document, and exposes a deterministic calculator tool. Vessel facts → totals with evidence and trace.

The split is deliberate:
- **LLM agents** read documents and emit `port_tariff.rule_pack.v1` JSON.
- **C++ core** evaluates rule packs deterministically. No models, no I/O, no hidden state.
- **Rule packs** are data, generated per port. The repository ships zero port-specific rules.

## Validated example — Port of Rotterdam, Annex 2 Example 4

> Container ship in Deepsea Service, GT 75,246, transhipment 15,000 t containers, ESI score 35.
>
> **Expected total: €21,808.74** · *Source: Port of Rotterdam — Port Tariffs 2026, Annex 2 Example 4 (page 20 of the PDF).*

End-to-end through the agent pipeline:

```
Upload Rotterdam PDF
  └─ Claude (claude-sonnet-4-6) reads the PDF natively, 4m38s
  └─ Extracts 106 rules covering Annex 1 Tables 1–4 + ESI bands + Green Award + special rates + waste fee + inland port dues
  └─ C++ core validates → activates calculator tool
Calculate vessel
  └─ Vessel component (Container Deepsea, GT × 0.151)         €11,362.15
  └─ Cargo component (Containers Deepsea, 15,000 t × 0.562)    €8,430.00
  └─ Sustainability component (GT × 0.067)                     €5,041.48
  └─ ESI 31–40 discount (60% off sustainability)              −€3,024.89
  └─ Total                                                    €21,808.74  ✓
```

**Identical to the published value, to the cent, through agent-extracted rules.** Reproducible: see `scripts/validate_rotterdam_examples.py`.

## Run

```bash
poc/port_tariff_agent/scripts/dev.sh   # build + serve
poc/port_tariff_agent/scripts/stop.sh  # kill PIDs in .run/
```

UI: `http://127.0.0.1:5179` · API: `http://127.0.0.1:8787/api/health`

The script configures CMake (`-DNBOT_ENABLE_PORT_TARIFF_POC=ON`), builds `port_tariff_core`, installs Python deps if missing, links `web/node_modules` from `tools/trajectory_lab/web/` if available, and launches API + Vite. Logs land in `.logs/`, PIDs in `.run/`.

## End-to-end flow

1. **Configure a provider** (gear icon → Settings drawer). Paste a Gemini and/or Anthropic API key. Keys persist locally in `.runtime/model_providers.local.json`.
2. **Upload a tariff PDF.** The pipeline reads the PDF natively (no PyPDF2 text stripping for supported providers) and produces:
   - `port_tariff.rule_pack.v1` (rates, applicability conditions, formulas, evidence, confidence)
   - `self_tests` — any worked examples it found in the document, with expected totals
3. **Self-test + refine.** The PoC immediately runs every `self_test` through the C++ core. If any total diverges by more than €1, the agent gets one refinement pass: it sees the original pack and the per-test diffs, and returns a corrected pack. The corrected pack is re-validated.
4. **Calculate.** Edit vessel facts in the calculator form (or paste raw JSON). The C++ core matches rules and evaluates formulas against your vessel; results show per-charge amounts, evidence page links, confidence, and the full execution trace.
5. **Switch ports.** Each upload produces a new "known port" entry. Switch between them via the dropdown without re-uploading.

The whole pipeline runs in the agent graph view — eight stages from `document_ingest` through `explain_trace`, with live cursor animation while the LLM is working and elapsed-time readouts during long PDF reads.

## How extraction actually works

Extraction is **multi-provider with fallback**: configured providers are tried in order, with the `default_research_provider` first. If Gemini times out (5 min cap) or returns invalid JSON, the next eligible provider (Claude, then any OpenAI-compatible endpoint) is tried. PDF input goes natively (`inline_data` for Gemini, `document` content block for Claude) so the model sees the original tables instead of flattened text. JSON sanitisation strips raw control characters; if the response is truncated mid-rule, the parser closes the rules array at the last complete object and salvages the partial pack.

Rule-level validation is lenient — rules with unsupported ops are dropped with a warning (`extraction_warnings`) instead of rejecting the whole pack. Empty packs are still rejected so the calculator never activates with zero rules.

## API

- `GET /api/health` — wrapper + core status, active port pointer.
- `GET /api/ports` — known ports list (each tied to a generated rule pack).
- `POST /api/ports/{port_id}/activate` — make this port's rule pack the active one.
- `GET /api/rules` — current active rule pack (or empty template).
- `GET /api/tools` · `GET /api/tools/{tool_id}` · `POST /api/tools/{tool_id}/execute` — calculator tool descriptor + execution.
- `POST /api/calculate` — accepts `{vessel, rule_pack?}`. If `rule_pack` is omitted, uses the active one. 409 if no rule pack is active.
- `POST /api/rule-pack/validate` — schema-check a rule pack via the C++ core without storing it.
- `POST /api/rule-pack/activate` — store and activate a rule pack JSON directly (used internally by upload + manual JSON imports).
- `POST /api/document/upload` — upload a tariff PDF/text. Returns `rule_generation` (extraction status, provider, attempts), `refinement` (self-test results, post-refine diffs), `activated_rule_pack` (only when both extraction and validation succeed), plus document analysis (page links, candidate term scan).
- `GET /api/document/{source_id}/page/{page}` — extracted page text (used by evidence links).
- `GET/POST /api/models[/configure]` — provider config; keys masked on read.
- `POST /api/research/clarify` — record a research dispatch (for the optional clarify stage).

## Rule pack contract

```json
{
  "schema_version": "port_tariff.rule_pack.v1",
  "document": {
    "title": "...",
    "source": "...",
    "jurisdiction": "...",
    "currency": "EUR"
  },
  "rules": [
    {
      "id": "vessel_dues.bulk_carrier",
      "charge_name": "Vessel component — Bulk carrier",
      "category": "seaport_dues_vessel",
      "applicability": [
        {"field": "technical_specs.type", "op": "eq_ci", "value": "bulk_carrier"},
        {"field": "technical_specs.gross_tonnage", "op": ">", "value": 0}
      ],
      "formula": {"op": "multiply", "args": [{"var": "technical_specs.gross_tonnage"}, {"const": 0.314}]},
      "evidence": [{"page": 14, "quote": "D Bulk carriers 0.314"}],
      "confidence": 0.95
    }
  ],
  "self_tests": [
    {
      "name": "Annex 2 Example 4",
      "vessel": {"technical_specs": {"gross_tonnage": 75246, "vessel_type_table1": "E"}, "operational_data": {"cargo_tonnes": 15000, "cargo_type_table2": "09", "service_type": "deepsea", "esi_score": 35}},
      "expected_total": 21808.74,
      "evidence": {"page": 20}
    }
  ]
}
```

**Formula DSL:** `const`, `var`, `add`, `subtract`, `multiply`, `divide`, `ceil_div`, `max`, `min`, `coalesce`. Variables (`var`) read dotted paths into the input vessel JSON.

**Applicability ops:** `eq_ci`, `in_ci`, `exists`, `>`, `>=`, `<`, `<=`, `==`/`eq`. The C++ matcher is case-insensitive for string compares. Anything else is rejected at validation.

## Refinement loop

When the LLM extracts `self_tests` from the document (Annex examples, validation tables, Step-N walkthroughs), the PoC uses them to self-correct:

1. Initial extraction → C++ validates → activate.
2. Run each `self_test` through the active pack.
3. For each test where `|actual − expected| > €1`:
   - Build a refinement prompt: original pack + per-test diff + applied charges.
   - Call the same provider (or fall through). Model returns the COMPLETE corrected pack.
   - C++ validates → re-run self-tests.
4. Result: `passed`, `refined_partial`, or `refine_validation_failed`. Surface in UI and activity log.

The loop is single-pass to keep upload time bounded. For complex tariffs with many derived discounts (efficiency caps, tier reductions, mutually exclusive incentives), additional manual refinement triggers can be added.

## Provider configuration

`data/model_providers.example.json` is the bundled defaults. Local overrides (with API keys) live in `.runtime/model_providers.local.json`, gitignored. Both Gemini and Claude are enabled by default with `api_key_env` fallbacks (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`) so env vars Just Work. Set `default_research_provider` to control which is tried first.

| Provider | Model default | PDF native input | Notes |
|---|---|---|---|
| `gemini` | `gemini-2.5-pro` | yes (`inline_data`) | fastest first attempt; can timeout on dense 25+ page PDFs |
| `claude` | `claude-sonnet-4-6` | yes (`document` block) | reliable fallback; 64k output tokens |
| `local-openai-compatible` | configurable | text only | for self-hosted models |

## What's NOT in the repo

No port-specific rule pack ships as default data. `data/empty_rule_pack.template.json` is a neutral boot template only. Calculator activates only after a successful upload + extraction + validation. This is intentional: the architectural pitch is that the agent extracts rules from documents, not that the system is a hand-curated calculator wearing an agent costume.

## Validation script

```bash
python3 poc/port_tariff_agent/scripts/validate_rotterdam_examples.py
```

Verifies the active rule pack reproduces the four Annex 2 examples from the Port of Rotterdam 2026 tariff. Use as a regression harness when iterating on prompts or the refinement loop.

## When changing things

- Adding a formula op or applicability op: update `core/src/FormulaEvaluator.cpp` / `RuleMatcher.cpp` plus the agent's `_validate_formula` / `_validate_condition` and the prompt's allowed-ops list.
- Adding a core CLI mode: add the arm in `core/src/CoreCli.cpp` and the matching `run_core("mode", ...)` site in `server.py`.
- Bumping the rule-pack schema version: every consumer (`CoreCli::validate_rule_pack`, `TariffToolFactory`, `RuleExtractionAgent._parse_rule_pack`) checks the literal `port_tariff.rule_pack.v1`.

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any


class RuleExtractionAgent:
    """Calls configured model providers to convert extracted tariff pages into rule packs."""

    FACT_ROOTS: tuple[str, ...] = (
        "technical_specs.",
        "operational_data.",
        "dimensions.",
        "identity.",
        "vessel.",
    )

    FACT_ALIASES: dict[str, str] = {
        "cargo_item.quantity_tonnes": "operational_data.cargo_tonnes",
        "cargo_item.type": "operational_data.cargo_type",
        "vessel_facts.service_type": "operational_data.service_type",
        "vessel_facts.vessel_type": "operational_data.vessel_type",
        "vessel_facts.esi_score": "operational_data.esi_score",
        "vessel_facts.has_green_award": "operational_data.has_green_award",
        "vessel_details.service_type": "operational_data.service_type",
        "vessel_details.vessel_type": "operational_data.vessel_type",
        "vessel_details.esi_score": "operational_data.esi_score",
        "vessel_details.has_green_award": "operational_data.has_green_award",
        "vessel.gt": "technical_specs.gross_tonnage",
        "technical_specs.gt": "technical_specs.gross_tonnage",
        "dimensions.gross_tonnage": "technical_specs.gross_tonnage",
    }

    def __init__(self, providers: dict[str, Any], prompt: str):
        self.providers = providers
        self.prompt = prompt

    def extract(
        self,
        filename: str,
        pages: list[dict[str, Any]],
        candidates: list[dict[str, str]],
        pdf_bytes: bytes | None = None,
    ) -> dict[str, Any]:
        """Generate a rule pack from document pages, falling back across providers on failure.

        When raw PDF bytes are supplied and a provider supports multimodal PDF input,
        the document is sent natively so the model sees the original tables instead of
        flattened OCR-style text. If the first eligible provider errors or times out,
        the next eligible provider is tried with the same input.
        """
        eligible = self._eligible_providers()
        if not eligible:
            return {
                "status": "needs_provider_config",
                "message": "Configure an enabled LLM provider/API key before automatic tariff rule extraction can run.",
                "candidate_terms": candidates,
            }

        attempts: list[dict[str, Any]] = []
        for provider in eligible:
            input_mode = "pdf_native" if (pdf_bytes and provider.get("kind") in {"gemini", "anthropic"}) else "page_text"
            try:
                if input_mode == "pdf_native":
                    prompt = self._build_native_pdf_prompt(filename, candidates)
                    text = self._call_provider_with_pdf(provider, prompt, pdf_bytes)
                else:
                    prompt = self._build_prompt(filename, pages, candidates)
                    text = self._call_provider(provider, prompt)
                rule_pack = self._parse_rule_pack(text)
            except Exception as exc:
                attempts.append({
                    "provider": self._public_provider(provider),
                    "input_mode": input_mode,
                    "error": str(exc),
                })
                continue

            return {
                "status": "generated",
                "provider": self._public_provider(provider),
                "rule_pack": rule_pack,
                "input_mode": input_mode,
                "attempts": attempts,
                "message": f"Generated {len(rule_pack.get('rules', []))} rules from {filename} via {provider.get('id')} ({input_mode}).",
            }

        return {
            "status": "failed",
            "provider": self._public_provider(eligible[-1]),
            "attempts": attempts,
            "message": "All eligible providers failed: " + "; ".join(
                f"{a['provider']['id']}: {a['error']}" for a in attempts
            ),
            "candidate_terms": candidates,
        }

    def refine(self, original_pack: dict[str, Any], diffs: list[dict[str, Any]], pdf_bytes: bytes | None = None) -> dict[str, Any]:
        """Ask the configured provider to fix a rule pack so its self_tests match expected totals.

        `diffs` is a list of {name, vessel, expected_total, actual_total, missing_amount,
        applied_charges, evidence_pages} entries — one per failing self-test. The model
        receives the original pack and these gaps, and must return a complete corrected pack.
        """
        eligible = self._eligible_providers()
        if not eligible:
            return {"status": "needs_provider_config", "message": "No provider available for refinement."}

        attempts: list[dict[str, Any]] = []
        for provider in eligible:
            input_mode = "pdf_native" if (pdf_bytes and provider.get("kind") in {"gemini", "anthropic"}) else "page_text"
            prompt = self._build_refinement_prompt(original_pack, diffs)
            try:
                if input_mode == "pdf_native":
                    text = self._call_provider_with_pdf(provider, prompt, pdf_bytes)
                else:
                    text = self._call_provider(provider, prompt)
                rule_pack = self._parse_rule_pack(text)
            except Exception as exc:
                attempts.append({
                    "provider": self._public_provider(provider),
                    "input_mode": input_mode,
                    "error": str(exc),
                })
                continue

            return {
                "status": "refined",
                "provider": self._public_provider(provider),
                "rule_pack": rule_pack,
                "input_mode": input_mode,
                "attempts": attempts,
                "message": f"Refined to {len(rule_pack.get('rules', []))} rules via {provider.get('id')}.",
            }

        return {
            "status": "failed",
            "attempts": attempts,
            "message": "All eligible providers failed during refinement.",
        }

    def _build_refinement_prompt(self, original_pack: dict[str, Any], diffs: list[dict[str, Any]]) -> str:
        """Compose a prompt that hands the model its previous output, the failing self-tests,
        and the exact totals it needs to hit. The model must return the COMPLETE updated pack.
        """
        diff_summary = json.dumps(diffs, indent=2, ensure_ascii=False)
        original_pack_json = json.dumps(original_pack, indent=2, ensure_ascii=False)
        return (
            f"{self.prompt}\n\n"
            "REFINEMENT TASK\n"
            "===============\n"
            "You produced this rule pack from the attached tariff document, but its self_tests\n"
            "do not match expected totals. Identify the missing or wrong rules, fix them, and\n"
            "return the COMPLETE corrected port_tariff.rule_pack.v1 JSON. Do not return diffs.\n"
            "Do not skip rules that were correct — keep them as-is. Add missing rules (especially\n"
            "derived discounts like efficiency caps written as `multiply(const -1, max(const 0, subtract(cargo_subtotal, cap_amount)))`).\n"
            "Make sure slugs (service_type, vessel_type_*, cargo_type_*) used in vessel rules,\n"
            "cargo rules, and self_tests are IDENTICAL strings.\n"
            "Return JSON only. Do not wrap in markdown.\n\n"
            f"FAILING SELF-TESTS WITH DIFFS:\n{diff_summary}\n\n"
            f"ORIGINAL RULE PACK:\n{original_pack_json}"
        )

    def _eligible_providers(self) -> list[dict[str, Any]]:
        """Return enabled providers with rule_extraction role and a usable key, default-first."""
        default_id = self.providers.get("default_research_provider")
        providers = [
            provider
            for provider in self.providers.get("providers", [])
            if provider.get("enabled") and "rule_extraction" in provider.get("roles", [])
        ]
        providers.sort(key=lambda provider: provider.get("id") != default_id)
        return [p for p in providers if self._api_key(p) or p.get("kind") == "openai_compatible"]

    def _select_provider(self) -> dict[str, Any] | None:
        eligible = self._eligible_providers()
        return eligible[0] if eligible else None

    def _api_key(self, provider: dict[str, Any]) -> str | None:
        if provider.get("api_key"):
            return provider["api_key"]
        env_name = provider.get("api_key_env")
        return os.environ.get(env_name) if env_name else None

    def _public_provider(self, provider: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": provider.get("id"),
            "kind": provider.get("kind"),
            "model": provider.get("model"),
            "endpoint": provider.get("endpoint"),
        }

    def _build_prompt(self, filename: str, pages: list[dict[str, Any]], candidates: list[dict[str, str]]) -> str:
        selected_pages = pages[:18]
        page_text = "\n\n".join(
            f"--- PAGE {page.get('page')} ---\n"
            f"HEADINGS: {json.dumps(page.get('headings', []), ensure_ascii=False)}\n"
            f"SIGNALS: {json.dumps(page.get('signals', []), ensure_ascii=False)}\n"
            f"SNIPPETS: {json.dumps(page.get('snippets', []), ensure_ascii=False)}\n"
            f"TEXT:\n{(page.get('text') or '')[:5000]}"
            for page in selected_pages
        )
        return (
            f"{self.prompt}\n\n"
            "Return JSON only. Do not wrap in markdown. The JSON must match port_tariff.rule_pack.v1.\n\n"
            f"UPLOAD_FILENAME: {filename}\n"
            f"CANDIDATE_TERMS: {json.dumps(candidates, ensure_ascii=False)}\n\n"
            f"EXTRACTED_PAGE_TEXT:\n{page_text}"
        )

    def _build_native_pdf_prompt(self, filename: str, candidates: list[dict[str, str]]) -> str:
        """Build the user-side prompt for multimodal PDF input.

        The PDF itself is attached as the first part of the request; the model reads
        the original tables and applicability text instead of stripped page text.
        """
        return (
            f"{self.prompt}\n\n"
            "The attached document is a port tariff PDF. Read every page, including the rate tables.\n"
            "Return JSON only. Do not wrap in markdown. The JSON must match port_tariff.rule_pack.v1.\n"
            "Every numeric constant in a `formula` MUST appear verbatim in the document and be cited in `evidence` with a page number and short quote.\n"
            "If a charge applies only to specific ports, vessel types, services, or cargo, encode that as `applicability` conditions on `operational_data.*` or `technical_specs.*` paths.\n"
            "Do not invent rates. If a rate is missing or ambiguous, surface it in `open_questions` rather than guessing.\n\n"
            f"UPLOAD_FILENAME: {filename}\n"
            f"CANDIDATE_TERMS: {json.dumps(candidates, ensure_ascii=False)}"
        )

    def _call_provider_with_pdf(self, provider: dict[str, Any], prompt: str, pdf_bytes: bytes) -> str:
        kind = provider.get("kind")
        if kind == "gemini":
            return self._call_gemini_pdf(provider, prompt, pdf_bytes)
        if kind == "anthropic":
            return self._call_anthropic_pdf(provider, prompt, pdf_bytes)
        raise RuntimeError(f"Provider kind {kind} does not support native PDF input.")

    def _call_provider(self, provider: dict[str, Any], prompt: str) -> str:
        kind = provider.get("kind")
        if kind == "gemini":
            return self._call_gemini(provider, prompt)
        if kind == "anthropic":
            return self._call_anthropic(provider, prompt)
        if kind == "openai_compatible":
            return self._call_openai_compatible(provider, prompt)
        raise RuntimeError(f"Unsupported provider kind: {kind}")

    def _call_gemini(self, provider: dict[str, Any], prompt: str) -> str:
        key = self._api_key(provider)
        if not key:
            raise RuntimeError("Gemini API key is not configured.")
        endpoint = provider.get("endpoint", "https://generativelanguage.googleapis.com").rstrip("/")
        model = provider.get("model", "gemini-1.5-pro")
        url = f"{endpoint}/v1beta/models/{model}:generateContent?key={key}"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "response_mime_type": "application/json", "maxOutputTokens": 32768},
        }
        data = self._post_json(url, payload, {})
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        return "\n".join(part.get("text", "") for part in parts)

    def _call_gemini_pdf(self, provider: dict[str, Any], prompt: str, pdf_bytes: bytes) -> str:
        key = self._api_key(provider)
        if not key:
            raise RuntimeError("Gemini API key is not configured.")
        endpoint = provider.get("endpoint", "https://generativelanguage.googleapis.com").rstrip("/")
        model = provider.get("model", "gemini-1.5-pro")
        url = f"{endpoint}/v1beta/models/{model}:generateContent?key={key}"
        encoded = base64.b64encode(pdf_bytes).decode("ascii")
        payload = {
            "contents": [{
                "role": "user",
                "parts": [
                    {"inline_data": {"mime_type": "application/pdf", "data": encoded}},
                    {"text": prompt},
                ],
            }],
            "generationConfig": {"temperature": 0.1, "response_mime_type": "application/json", "maxOutputTokens": 32768},
        }
        data = self._post_json(url, payload, {})
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        return "\n".join(part.get("text", "") for part in parts)

    def _call_anthropic(self, provider: dict[str, Any], prompt: str) -> str:
        key = self._api_key(provider)
        if not key:
            raise RuntimeError("Anthropic API key is not configured.")
        endpoint = provider.get("endpoint", "https://api.anthropic.com").rstrip("/")
        payload = {
            "model": provider.get("model", "claude-sonnet-4-6"),
            "max_tokens": 64000,
            "temperature": 0.1,
            "messages": [{"role": "user", "content": prompt}],
        }
        data = self._post_json(
            f"{endpoint}/v1/messages",
            payload,
            {"x-api-key": key, "anthropic-version": "2023-06-01"},
        )
        return "\n".join(part.get("text", "") for part in data.get("content", []) if part.get("type") == "text")

    def _call_anthropic_pdf(self, provider: dict[str, Any], prompt: str, pdf_bytes: bytes) -> str:
        key = self._api_key(provider)
        if not key:
            raise RuntimeError("Anthropic API key is not configured.")
        endpoint = provider.get("endpoint", "https://api.anthropic.com").rstrip("/")
        encoded = base64.b64encode(pdf_bytes).decode("ascii")
        payload = {
            "model": provider.get("model", "claude-sonnet-4-6"),
            "max_tokens": 64000,
            "temperature": 0.1,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": encoded}},
                    {"type": "text", "text": prompt},
                ],
            }],
        }
        data = self._post_json(
            f"{endpoint}/v1/messages",
            payload,
            {"x-api-key": key, "anthropic-version": "2023-06-01"},
        )
        return "\n".join(part.get("text", "") for part in data.get("content", []) if part.get("type") == "text")

    def _call_openai_compatible(self, provider: dict[str, Any], prompt: str) -> str:
        endpoint = provider.get("endpoint", "http://127.0.0.1:8000/v1").rstrip("/")
        headers = {}
        key = self._api_key(provider)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        payload = {
            "model": provider.get("model", "local-tariff-reasoner"),
            "temperature": 0.1,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        data = self._post_json(f"{endpoint}/chat/completions", payload, headers)
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")

    def _post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Provider HTTP {exc.code}: {detail[:1200]}") from exc

    def _parse_rule_pack(self, text: str) -> dict[str, Any]:
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
            stripped = re.sub(r"```$", "", stripped).strip()
        match = re.search(r"\{.*\}", stripped, flags=re.S)
        if not match:
            raise RuntimeError("Provider did not return a JSON object.")
        candidate = self._sanitize_json_text(match.group(0))
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            repaired = self._repair_truncated_rule_pack(candidate)
            if repaired is None:
                raise RuntimeError(f"{exc}; provider output could not be repaired") from exc
            parsed = json.loads(repaired)
            parsed.setdefault("extraction_warnings", []).append({
                "rule_id": None,
                "error": f"Provider response was truncated; auto-recovered up to char {exc.pos}.",
            })
        if parsed.get("schema_version") != "port_tariff.rule_pack.v1":
            raise RuntimeError("Provider JSON is not port_tariff.rule_pack.v1.")
        if not isinstance(parsed.get("rules"), list):
            raise RuntimeError("Provider JSON has no rules array.")
        if not parsed.get("rules"):
            raise RuntimeError("Provider returned no tariff rules; calculation cannot be activated from an empty pack.")
        self._normalize_rule_pack(parsed)
        warnings = self._filter_invalid_rules(parsed)
        if warnings:
            parsed.setdefault("extraction_warnings", []).extend(warnings)
        if not parsed.get("rules"):
            raise RuntimeError(
                f"Every rule the provider returned was unusable. First error: {warnings[0]['error']}"
                if warnings else "Provider returned no usable rules."
            )
        return parsed

    def _sanitize_json_text(self, text: str) -> str:
        """Strip raw control characters that LLMs sometimes emit inside string literals.

        Gemini in particular occasionally pastes raw newlines or tabs into evidence
        `quote` fields, which json.loads rejects. Removing only the unescaped control
        chars (0x00-0x1F except \\t \\n \\r) keeps the JSON parseable without altering
        meaningful content.
        """
        cleaned: list[str] = []
        in_string = False
        escape = False
        for ch in text:
            code = ord(ch)
            if escape:
                cleaned.append(ch)
                escape = False
                continue
            if ch == "\\" and in_string:
                cleaned.append(ch)
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                cleaned.append(ch)
                continue
            if in_string and code < 0x20 and ch not in ("\t", "\n", "\r"):
                cleaned.append(" ")
                continue
            if in_string and ch in ("\n", "\r", "\t"):
                cleaned.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}[ch])
                continue
            cleaned.append(ch)
        return "".join(cleaned)

    def _repair_truncated_rule_pack(self, text: str) -> str | None:
        """Recover a parseable rule pack from a response truncated mid-rule.

        Locates the start of the rules array, walks balanced brace depth to find the
        last complete rule object, then closes the array and the document with the
        appropriate `]}`.
        """
        rules_marker = re.search(r'"rules"\s*:\s*\[', text)
        if not rules_marker:
            return None
        start = rules_marker.end()
        depth = 0
        in_string = False
        escape = False
        last_complete = None
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\" and in_string:
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    last_complete = i + 1
        if last_complete is None or last_complete <= start:
            return None
        return text[:last_complete] + "]}"

    def _filter_invalid_rules(self, rule_pack: dict[str, Any]) -> list[dict[str, Any]]:
        """Drop rules that violate the executable DSL; keep the rest. Return per-rule error notes."""
        kept: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        for index, rule in enumerate(rule_pack.get("rules", [])):
            try:
                self._validate_one_rule(rule)
                kept.append(rule)
            except Exception as exc:
                warnings.append({
                    "rule_id": rule.get("id") if isinstance(rule, dict) else None,
                    "rule_index": index,
                    "charge_name": rule.get("charge_name") if isinstance(rule, dict) else None,
                    "error": str(exc),
                })
        rule_pack["rules"] = kept
        return warnings

    def _validate_one_rule(self, rule: Any) -> None:
        """Validate a single rule against the executable DSL. Raises on any violation."""
        if not isinstance(rule, dict):
            raise RuntimeError("Rule is not an object.")
        if not rule.get("id") or not rule.get("charge_name"):
            raise RuntimeError("Rule is missing id or charge_name.")
        applicability = rule.get("applicability", [])
        if not isinstance(applicability, list):
            raise RuntimeError(f"Rule {rule.get('id')} applicability must be an array.")
        for condition in applicability:
            self._validate_condition(rule.get("id"), condition)
        self._validate_formula(rule.get("id"), rule.get("formula"))
        evidence = rule.get("evidence", [])
        if evidence is not None and not isinstance(evidence, list):
            raise RuntimeError(f"Rule {rule.get('id')} evidence must be an array.")
        if "confidence" in rule and not isinstance(rule.get("confidence"), (int, float)):
            raise RuntimeError(f"Rule {rule.get('id')} confidence must be numeric.")

    def _normalize_rule_pack(self, rule_pack: dict[str, Any]) -> None:
        """Normalize harmless provider shape variations without changing rule meaning."""
        for rule in rule_pack.get("rules", []):
            if not isinstance(rule, dict):
                continue
            if isinstance(rule.get("applicability"), dict):
                rule["applicability"] = [rule["applicability"]]
            if isinstance(rule.get("evidence"), dict):
                rule["evidence"] = [rule["evidence"]]
            if isinstance(rule.get("evidence"), str):
                rule["evidence"] = [{"quote": rule["evidence"]}]
            if isinstance(rule.get("notes"), list):
                rule["notes"] = " ".join(str(note) for note in rule["notes"] if note)
            if isinstance(rule.get("notes"), dict):
                rule["notes"] = json.dumps(rule["notes"], ensure_ascii=False)
            if isinstance(rule.get("confidence"), str):
                rule["confidence"] = self._normalize_confidence(rule["confidence"])
            for condition in rule.get("applicability", []) if isinstance(rule.get("applicability", []), list) else []:
                if isinstance(condition, dict) and isinstance(condition.get("field"), str):
                    condition["field"] = self._normalize_fact_path(condition["field"])
            self._normalize_formula_paths(rule.get("formula"))

    def _validate_rule_pack(self, rule_pack: dict[str, Any]) -> None:
        """Reject model output that is JSON but not executable by the deterministic core."""
        for rule in rule_pack.get("rules", []):
            self._validate_one_rule(rule)

    def _normalize_confidence(self, value: str) -> float:
        """Convert common confidence labels into numeric values for the C++ result schema."""
        normalized = value.strip().lower()
        if normalized in {"high", "strong"}:
            return 0.9
        if normalized in {"medium", "moderate"}:
            return 0.65
        if normalized in {"low", "weak"}:
            return 0.35
        try:
            return float(normalized)
        except ValueError:
            return 0.5

    def _validate_condition(self, rule_id: str | None, condition: Any) -> None:
        """Validate one applicability condition in the core condition DSL."""
        if not isinstance(condition, dict):
            raise RuntimeError(f"Rule {rule_id} has a non-object applicability condition.")
        if not isinstance(condition.get("field"), str) or not condition.get("field"):
            raise RuntimeError(f"Rule {rule_id} condition is missing field.")
        if not condition["field"].startswith(self.FACT_ROOTS):
            raise RuntimeError(f"Rule {rule_id} condition references unsupported fact path `{condition['field']}`.")
        if condition.get("op") not in {"exists", "eq_ci", "in_ci", ">", ">=", "<", "<=", "==", "eq"}:
            raise RuntimeError(f"Rule {rule_id} condition has unsupported op: {condition.get('op')}.")
        if condition.get("op") != "exists" and "value" not in condition:
            raise RuntimeError(f"Rule {rule_id} condition is missing value.")

    def _validate_formula(self, rule_id: str | None, formula: Any) -> None:
        """Validate one formula expression in the core formula DSL."""
        if isinstance(formula, (int, float)):
            return
        if not isinstance(formula, dict):
            raise RuntimeError(f"Rule {rule_id} formula must be a JSON object, not {type(formula).__name__}.")
        if "const" in formula:
            if not isinstance(formula["const"], (int, float)):
                raise RuntimeError(f"Rule {rule_id} const formula must be numeric.")
            return
        if "var" in formula:
            if not isinstance(formula["var"], str) or not formula["var"]:
                raise RuntimeError(f"Rule {rule_id} var formula must be a non-empty string.")
            if not formula["var"].startswith(self.FACT_ROOTS):
                raise RuntimeError(
                    f"Rule {rule_id} formula references non-input variable `{formula['var']}`. "
                    "The current C++ core executes independent payable rules, not generated-rule DAG state."
                )
            return
        if formula.get("op") not in {"add", "subtract", "multiply", "divide", "ceil_div", "max", "min", "coalesce"}:
            raise RuntimeError(f"Rule {rule_id} formula has unsupported op: {formula.get('op')}.")
        args = formula.get("args")
        if not isinstance(args, list) or not args:
            raise RuntimeError(f"Rule {rule_id} formula op requires non-empty args.")
        for arg in args:
            self._validate_formula(rule_id, arg)

    def _normalize_fact_path(self, path: str) -> str:
        """Map common provider fact-path variants into the canonical vessel schema."""
        if path in self.FACT_ALIASES:
            return self.FACT_ALIASES[path]
        for prefix in ("vessel_facts.", "vessel_details."):
            if path.startswith(prefix):
                return f"operational_data.{path[len(prefix):]}"
        return path

    def _normalize_formula_paths(self, formula: Any) -> None:
        """Normalize fact paths inside formula trees in place."""
        if isinstance(formula, dict):
            if isinstance(formula.get("var"), str):
                formula["var"] = self._normalize_fact_path(formula["var"])
            for value in formula.values():
                self._normalize_formula_paths(value)
        elif isinstance(formula, list):
            for item in formula:
                self._normalize_formula_paths(item)

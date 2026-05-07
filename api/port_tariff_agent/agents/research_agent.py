from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any


class ResearchAgent:
    """Calls a configured model provider to clarify ambiguous tariff context.

    Given a question and optional grounding (vessel facts, rule pack excerpts,
    document pages), the agent prompts the configured provider and returns a
    structured `port_tariff.research_result.v1` answer with citations.
    """

    def __init__(self, providers: dict[str, Any], prompt: str):
        self.providers = providers
        self.prompt = prompt

    def clarify(self, query: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a research clarification through the first eligible provider.

        Eligible = enabled + has key/api_key_env + has the `ambiguity_research`
        role. If no provider qualifies, returns `needs_provider_config` so the
        UI can surface an actionable next step rather than pretending an answer
        was generated.
        """
        eligible = self._eligible_providers()
        if not eligible:
            return {
                "schema_version": "port_tariff.research_result.v1",
                "status": "needs_provider_config",
                "question": query,
                "message": "Configure an enabled LLM provider/API key with the `ambiguity_research` role.",
            }

        attempts: list[dict[str, Any]] = []
        for provider in eligible:
            try:
                text = self._call_provider(provider, self._build_prompt(query, context))
                parsed = self._parse_research_result(text, query)
                return {
                    **parsed,
                    "provider": self._public_provider(provider),
                    "attempts": attempts,
                }
            except Exception as exc:
                attempts.append({
                    "provider": self._public_provider(provider),
                    "error": str(exc),
                })
                continue

        return {
            "schema_version": "port_tariff.research_result.v1",
            "status": "blocked",
            "question": query,
            "message": "All eligible providers failed.",
            "attempts": attempts,
        }

    def _eligible_providers(self) -> list[dict[str, Any]]:
        default_id = self.providers.get("default_research_provider")
        providers = [
            provider
            for provider in self.providers.get("providers", [])
            if provider.get("enabled") and "ambiguity_research" in (provider.get("roles") or [])
        ]
        providers.sort(key=lambda provider: provider.get("id") != default_id)
        return [p for p in providers if self._api_key(p) or p.get("kind") == "openai_compatible"]

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

    def _build_prompt(self, query: str, context: dict[str, Any] | None) -> str:
        ctx = context or {}
        page_excerpts = self._page_excerpts(ctx.get("pages") or [])
        return (
            f"{self.prompt}\n\n"
            "Return JSON only. Do not wrap in markdown. The JSON must match port_tariff.research_result.v1.\n"
            "If the answer can be found in the document pages provided below, prefer cite-from-document over external claims and set `source_type: \"document\"` with the page number.\n"
            "Be concise. Findings should be at most 5 entries.\n\n"
            f"QUESTION: {query}\n\n"
            f"VESSEL_CONTEXT: {json.dumps(ctx.get('vessel') or {}, ensure_ascii=False)}\n\n"
            f"RULE_PACK_HINTS: {json.dumps(ctx.get('rule_pack_hints') or {}, ensure_ascii=False)}\n\n"
            f"DOCUMENT_PAGES:\n{page_excerpts}"
        )

    def _page_excerpts(self, pages: list[dict[str, Any]]) -> str:
        if not pages:
            return "(none provided)"
        snippets: list[str] = []
        for page in pages[:8]:
            text = (page.get("text") or "")[:2400]
            snippets.append(f"--- PAGE {page.get('page')} ---\n{text}")
        return "\n\n".join(snippets)

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
        model = provider.get("model", "gemini-2.5-pro")
        url = f"{endpoint}/v1beta/models/{model}:generateContent?key={key}"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "response_mime_type": "application/json", "maxOutputTokens": 4096},
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
            "max_tokens": 4096,
            "temperature": 0.1,
            "messages": [{"role": "user", "content": prompt}],
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
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Provider HTTP {exc.code}: {detail[:1200]}") from exc

    def _parse_research_result(self, text: str, fallback_question: str) -> dict[str, Any]:
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
            stripped = re.sub(r"```$", "", stripped).strip()
        match = re.search(r"\{.*\}", stripped, flags=re.S)
        if not match:
            raise RuntimeError("Provider did not return a JSON object.")
        parsed = json.loads(match.group(0))
        parsed.setdefault("schema_version", "port_tariff.research_result.v1")
        parsed.setdefault("status", "answered")
        parsed.setdefault("question", fallback_question)
        if not isinstance(parsed.get("findings"), list):
            parsed["findings"] = []
        return parsed

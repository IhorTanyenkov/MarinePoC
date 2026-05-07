from __future__ import annotations

import re
from typing import Any


class TariffToolFactory:
    """Compiles a tariff rule pack into a callable port-specific tool contract."""

    def __init__(self, rule_pack: dict[str, Any]):
        self.rule_pack = rule_pack

    def descriptor(self) -> dict[str, Any]:
        """Return the tool descriptor an agent can call after rule extraction."""
        document = self.rule_pack.get("document", {})
        return {
            "schema_version": "nbot.tool_descriptor.v1",
            "tool_id": self.tool_id(),
            "name": "calculate_port_tariffs",
            "title": f"Calculate tariffs for {document.get('title', 'uploaded port tariff')}",
            "description": "Calculates vessel dues using the extracted tariff rules for this port/document.",
            "runtime": "nbot_lite_cpp_core",
            "endpoint": f"/api/tools/{self.tool_id()}/execute",
            "input_schema": self.input_schema(),
            "output_schema": self.output_schema(),
            "rule_pack": {
                "schema_version": self.rule_pack.get("schema_version"),
                "document": document,
                "rule_count": len(self.rule_pack.get("rules", [])),
                "charge_names": sorted({rule.get("charge_name", "Unnamed") for rule in self.rule_pack.get("rules", [])}),
            },
            "evidence_policy": {
                "required": True,
                "result_rows_include": ["reason", "evidence", "evidence_links", "confidence"],
            },
            "satellite_params": {
                "core_mode": "calculate",
                "rule_pack_injected_as_data": True,
                "model_calls_allowed": False,
            },
        }

    def tool_id(self) -> str:
        """Build a stable readable tool id from document metadata."""
        document = self.rule_pack.get("document", {})
        raw = "_".join(
            part
            for part in [
                document.get("jurisdiction", ""),
                document.get("title", ""),
                document.get("currency", ""),
            ]
            if part
        )
        normalized = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")
        return f"tariff_calc_{normalized or 'uploaded'}"

    def input_schema(self) -> dict[str, Any]:
        """Describe vessel and operation fields used by the extracted rules."""
        return {
            "type": "object",
            "required": ["vessel"],
            "properties": {
                "vessel": {
                    "type": "object",
                    "description": "Vessel and operation facts. Required nested fields are inferred from extracted rules.",
                    "x-required_fact_paths": sorted(self._variables_from_rules()),
                },
                "options": {
                    "type": "object",
                    "properties": {
                        "include_skipped_rules": {"type": "boolean", "default": True},
                        "include_evidence": {"type": "boolean", "default": True},
                    },
                },
            },
        }

    def output_schema(self) -> dict[str, Any]:
        """Describe deterministic calculation output."""
        return {
            "type": "object",
            "required": ["total", "results"],
            "properties": {
                "total": {"type": "number"},
                "results": {"type": "array"},
                "skipped_rules": {"type": "array"},
                "execution_trace": {"type": "array"},
            },
        }

    def _variables_from_rules(self) -> set[str]:
        variables: set[str] = set()
        for rule in self.rule_pack.get("rules", []):
            self._collect_variables(rule.get("formula", {}), variables)
            for condition in rule.get("applicability", []):
                if not isinstance(condition, dict):
                    continue
                field = condition.get("field")
                if field:
                    variables.add(field)
        return variables

    def _collect_variables(self, node: Any, variables: set[str]) -> None:
        if isinstance(node, dict):
            if "var" in node:
                variables.add(node["var"])
            for value in node.values():
                self._collect_variables(value, variables)
        elif isinstance(node, list):
            for item in node:
                self._collect_variables(item, variables)

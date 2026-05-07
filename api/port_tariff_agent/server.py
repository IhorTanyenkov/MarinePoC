from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from port_tariff_agent.agents.research_agent import ResearchAgent
from port_tariff_agent.agents.rule_extraction_agent import RuleExtractionAgent
from port_tariff_agent.tools.document_tools import DocumentTools
from port_tariff_agent.tools.tariff_tool_factory import TariffToolFactory

POC = Path(__file__).resolve().parents[2]
CORE = Path(os.environ.get("PORT_TARIFF_CORE_BIN", POC / "build" / "port_tariff_core"))
RULES_ENV = os.environ.get("PORT_TARIFF_RULES")
TEMPLATE_RULES = POC / "data" / "empty_rule_pack.template.json"
FIXTURE = Path(os.environ.get("PORT_TARIFF_FIXTURE", POC / "data" / "empty_vessel.template.json"))
PROVIDERS = Path(os.environ.get("PORT_TARIFF_PROVIDERS", POC / "data" / "model_providers.example.json"))
GRAPH = POC / "data" / "agent_graph.json"
RUNTIME = Path(os.environ.get("PORT_TARIFF_RUNTIME", POC / ".runtime"))
DOCUMENTS = RUNTIME / "documents"
MODEL_CONFIG = RUNTIME / "model_providers.local.json"
ACTIVE_RULE_PACK = RUNTIME / "active_rule_pack.json"
ACTIVE_PORT = RUNTIME / "active_port.json"
RULE_PACKS = RUNTIME / "rule_packs"


class CalculateRequest(BaseModel):
    vessel: dict[str, Any] | None = None
    rule_pack: dict[str, Any] | None = None


class ResearchRequest(BaseModel):
    query: str
    context: dict[str, Any] | None = None


class ModelProviderUpdate(BaseModel):
    id: str
    kind: str | None = None
    endpoint: str | None = None
    model: str | None = None
    api_key: str | None = None
    api_key_env: str | None = None
    enabled: bool | None = None
    roles: list[str] | None = None


class ModelConfigRequest(BaseModel):
    default_research_provider: str | None = None
    providers: list[ModelProviderUpdate]


class ToolExecuteRequest(BaseModel):
    vessel: dict[str, Any]
    options: dict[str, Any] | None = None


class ActivateRulePackRequest(BaseModel):
    rule_pack: dict[str, Any]
    source_id: str | None = None


app = FastAPI(title="NBot Lite Port Tariff Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return normalized or "uploaded_port"


def active_rule_pack_path() -> Path:
    if RULES_ENV:
        return Path(RULES_ENV)
    active = load_json(ACTIVE_PORT) if ACTIVE_PORT.exists() else {}
    if active.get("rule_pack_path"):
        candidate = Path(active["rule_pack_path"])
        if candidate.exists():
            return candidate
    return TEMPLATE_RULES


def active_rule_pack() -> dict[str, Any]:
    return load_json(active_rule_pack_path())


def has_generated_rule_pack() -> bool:
    return active_rule_pack_path() != TEMPLATE_RULES


def active_port_state() -> dict[str, Any]:
    return load_json(ACTIVE_PORT) if ACTIVE_PORT.exists() else {}


def rule_pack_id(pack: dict[str, Any]) -> str:
    document = pack.get("document", {})
    raw = " ".join(
        str(part)
        for part in [document.get("jurisdiction"), document.get("title"), document.get("source")]
        if part
    )
    return slug(raw)


def rule_pack_summary(path: Path) -> dict[str, Any]:
    pack = load_json(path)
    document = pack.get("document", {})
    return {
        "port_id": path.stem,
        "kind": "rule_pack",
        "title": document.get("title", path.stem),
        "jurisdiction": document.get("jurisdiction"),
        "source": document.get("source"),
        "currency": document.get("currency"),
        "rule_count": len(pack.get("rules", [])),
        "path": str(path),
    }


def known_ports() -> list[dict[str, Any]]:
    ports: dict[str, dict[str, Any]] = {}
    for doc in document_tools().list_documents():
        ports[doc["source_id"]] = {
            "port_id": doc["source_id"],
            "kind": "document",
            "title": doc.get("filename"),
            "source_id": doc["source_id"],
            "page_count": doc.get("page_count", 0),
            "has_rule_pack": False,
        }
    if RULE_PACKS.exists():
        for path in sorted(RULE_PACKS.glob("*.json")):
            summary = rule_pack_summary(path)
            source_id = load_json(path).get("_runtime", {}).get("source_id")
            port_id = source_id or summary["port_id"]
            existing = ports.get(port_id, {})
            ports[port_id] = {
                **existing,
                **summary,
                "port_id": port_id,
                "rule_pack_path": str(path),
                "has_rule_pack": True,
            }
    return sorted(ports.values(), key=lambda item: (not item.get("has_rule_pack"), item.get("title") or ""))


def activate_port(port_id: str) -> dict[str, Any]:
    for port in known_ports():
        if port.get("port_id") == port_id:
            if not port.get("has_rule_pack"):
                raise HTTPException(status_code=409, detail="This known port has no generated rule pack yet")
            state = {"port_id": port_id, "rule_pack_path": port["rule_pack_path"]}
            if port.get("source_id"):
                state["source_id"] = port["source_id"]
            write_json(ACTIVE_PORT, state)
            return port
    raise HTTPException(status_code=404, detail="Known port not found")


def raw_provider_config() -> dict[str, Any]:
    """Return merged provider config with secrets intact for backend adapters."""
    base = load_json(PROVIDERS)
    if MODEL_CONFIG.exists():
        local = load_json(MODEL_CONFIG)
        by_id = {provider["id"]: provider for provider in base.get("providers", [])}
        for provider in local.get("providers", []):
            by_id[provider["id"]] = {**by_id.get(provider["id"], {}), **provider}
        base["providers"] = list(by_id.values())
        if local.get("default_research_provider"):
            base["default_research_provider"] = local["default_research_provider"]
    return base


def active_providers() -> dict[str, Any]:
    return mask_provider_keys(raw_provider_config())


def mask_provider_keys(config: dict[str, Any]) -> dict[str, Any]:
    copied = json.loads(json.dumps(config))
    for provider in copied.get("providers", []):
        raw = provider.pop("api_key", None)
        if raw:
            provider["api_key_set"] = True
            provider["api_key_preview"] = f"{raw[:4]}...{raw[-4:]}" if len(raw) >= 8 else "***"
        else:
            key_env = provider.get("api_key_env")
            provider["api_key_set"] = bool(key_env and os.environ.get(key_env))
    return copied


def document_tools() -> DocumentTools:
    return DocumentTools(RUNTIME)


def rule_extraction_agent() -> RuleExtractionAgent:
    return RuleExtractionAgent(raw_provider_config(), (POC / "prompts" / "rule_extraction_agent.md").read_text())


def run_core(mode: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not CORE.exists():
        raise HTTPException(status_code=503, detail=f"C++ core not built: {CORE}")

    args = [
        str(CORE),
        "--mode",
        mode,
        "--rules",
        str(active_rule_pack_path()),
        "--fixture",
        str(FIXTURE),
        "--providers",
        str(PROVIDERS),
    ]

    temp_path: Path | None = None
    try:
        if payload is not None:
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as temp:
                json.dump(payload, temp)
                temp_path = Path(temp.name)
            args.extend(["--input", str(temp_path)])

        completed = subprocess.run(args, check=False, text=True, capture_output=True)
        if completed.returncode != 0:
            raise HTTPException(status_code=422, detail=completed.stderr.strip() or completed.stdout.strip())
        return json.loads(completed.stdout)
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


def run_self_tests(rule_pack: dict[str, Any]) -> list[dict[str, Any]]:
    """Run any `self_tests` embedded in a rule pack through the deterministic core.

    Returns one diff entry per test with both the actual and expected totals plus the
    applied per-charge amounts, so a refinement prompt can ask the model to close
    specific gaps. Tests with empty/zero `expected_total` are skipped.
    """
    tests = rule_pack.get("self_tests") or []
    diffs: list[dict[str, Any]] = []
    for index, test in enumerate(tests):
        if not isinstance(test, dict):
            continue
        vessel = test.get("vessel") or {}
        expected = test.get("expected_total")
        if not isinstance(expected, (int, float)):
            continue
        try:
            result = run_core("calculate", {"vessel": vessel, "rule_pack": rule_pack})
        except HTTPException as exc:
            diffs.append({
                "index": index,
                "name": test.get("name", f"self_test_{index}"),
                "expected_total": expected,
                "actual_total": None,
                "core_error": str(exc.detail) if hasattr(exc, "detail") else str(exc),
            })
            continue
        actual = result.get("total", 0)
        diff_amount = round(actual - expected, 2)
        if abs(diff_amount) < 1.0:
            continue
        diffs.append({
            "index": index,
            "name": test.get("name", f"self_test_{index}"),
            "expected_total": expected,
            "actual_total": actual,
            "missing_amount": -diff_amount,
            "applied_charges": [
                {"rule_id": row.get("rule_id"), "charge_name": row.get("charge_name"), "amount": row.get("amount"), "error": row.get("error")}
                for row in result.get("results", [])
            ],
            "skipped_rules": result.get("skipped_rules", []),
            "vessel": vessel,
            "expected_charges": test.get("expected_charges"),
        })
    return diffs


def store_generated_rule_pack(rule_pack: dict[str, Any], source_id: str | None) -> dict[str, Any]:
    if not rule_pack.get("rules"):
        raise HTTPException(status_code=422, detail={"ok": False, "message": "Generated rule pack has no rules; refusing to activate calculator."})
    validation = run_core("validate-rule-pack", rule_pack)
    if not validation.get("ok"):
        raise HTTPException(status_code=422, detail=validation)
    pack_id = rule_pack_id(rule_pack)
    stored = json.loads(json.dumps(rule_pack))
    stored["_runtime"] = {
        **stored.get("_runtime", {}),
        "source_id": source_id,
        "generated": True,
    }
    path = RULE_PACKS / f"{pack_id}.json"
    write_json(path, stored)
    write_json(ACTIVE_PORT, {"port_id": source_id or pack_id, "rule_pack_path": str(path), "source_id": source_id})
    return {
        "ok": True,
        "message": "Generated rule pack activated for calculator tools.",
        "port": active_port_state(),
        "rules": rules(),
        "tools": tools(),
        "validation": validation,
    }


def extract_text_from_upload(filename: str, data: bytes) -> list[dict[str, Any]]:
    return document_tools().extract_pages(filename, data)


def store_document(filename: str, data: bytes, pages: list[dict[str, Any]]) -> dict[str, Any]:
    return document_tools().store(filename, data, pages)


def active_document() -> dict[str, Any] | None:
    return document_tools().active_document()


def charge_reason(row: dict[str, Any]) -> str:
    if row.get("error"):
        return ""
    evidence = row.get("evidence") or []
    page = evidence[0].get("page") if evidence else None
    confidence = round((row.get("confidence") or 0) * 100)
    page_text = f" Evidence page {page}." if page else ""
    return (
        f"{row.get('charge_name', 'Charge')} applied at {row.get('amount')}. "
        f"Confidence {confidence}%.{page_text}"
    )


def enrich_result(result: dict[str, Any]) -> dict[str, Any]:
    doc = active_document()
    source_id = doc["source_id"] if doc else "generated"
    for row in result.get("results", []):
        row["reason"] = charge_reason(row)
        links = []
        for evidence in row.get("evidence") or []:
            page = evidence.get("page")
            if page:
                links.append(
                    {
                        "label": f"{doc['filename'] if doc else 'Generated rule pack'} p.{page}",
                        "url": f"/api/document/{source_id}/page/{page}",
                        "page": page,
                    }
                )
        row["evidence_links"] = links
    graph = load_json(GRAPH)
    result["execution_trace"] = [
        {
            "node_id": node["id"],
            "label": node["label"],
            "owner": node.get("owner"),
            "status": "complete" if node["id"] not in {"research_clarify"} else "available_when_needed",
            "detail": "Completed in this PoC run." if node["id"] != "research_clarify" else "Triggered when document ambiguity requires model/web clarification.",
        }
        for node in graph.get("nodes", [])
    ]
    return result


@app.get("/api/health")
def health() -> dict[str, Any]:
    core = run_core("health")
    return {
        **core,
        "api": "fastapi",
        "graph": str(GRAPH),
        "active_rule_pack_generated": has_generated_rule_pack(),
        "active_port": active_port_state(),
        "rule_updates_require_recompile": False,
    }


@app.get("/api/ports")
def ports() -> dict[str, Any]:
    return {
        "schema_version": "port_tariff.known_ports.v1",
        "active": active_port_state(),
        "ports": known_ports(),
    }


@app.post("/api/ports/{port_id}/activate")
def activate_known_port(port_id: str) -> dict[str, Any]:
    port = activate_port(port_id)
    return {
        "ok": True,
        "message": f"Activated {port.get('title') or port_id}.",
        "active": active_port_state(),
        "rules": rules(),
        "tools": tools(),
    }


@app.get("/api/rules")
def rules() -> dict[str, Any]:
    pack = active_rule_pack()
    pack["_runtime"] = {
        "active_rule_pack_generated": has_generated_rule_pack(),
        "path": str(active_rule_pack_path()),
        "active_port": active_port_state(),
        "message": "No generated tariff rules are active yet." if not has_generated_rule_pack() else "Generated tariff rules are active.",
    }
    return pack


@app.get("/api/tools")
def tools() -> dict[str, Any]:
    if not has_generated_rule_pack():
        return {
            "schema_version": "nbot.tools.v1",
            "tools": [],
            "message": "Upload/generate a rule pack before a calculator tool is available.",
        }
    return {
        "schema_version": "nbot.tools.v1",
        "tools": [TariffToolFactory(active_rule_pack()).descriptor()],
    }


@app.get("/api/tools/{tool_id}")
def tool_descriptor(tool_id: str) -> dict[str, Any]:
    if not has_generated_rule_pack():
        raise HTTPException(status_code=404, detail="No generated rule pack is active")
    descriptor = TariffToolFactory(active_rule_pack()).descriptor()
    if descriptor["tool_id"] != tool_id:
        raise HTTPException(status_code=404, detail="Tool not found for active rule pack")
    return descriptor


@app.post("/api/tools/{tool_id}/execute")
def execute_tool(tool_id: str, req: ToolExecuteRequest) -> dict[str, Any]:
    if not has_generated_rule_pack():
        raise HTTPException(status_code=409, detail="No generated rule pack is active")
    rule_pack = active_rule_pack()
    descriptor = TariffToolFactory(rule_pack).descriptor()
    if descriptor["tool_id"] != tool_id:
        raise HTTPException(status_code=404, detail="Tool not found for active rule pack")
    return enrich_result(run_core("calculate", {"vessel": req.vessel, "rule_pack": rule_pack}))


@app.get("/api/models")
def models() -> dict[str, Any]:
    return active_providers()


@app.post("/api/models/configure")
def configure_models(req: ModelConfigRequest) -> dict[str, Any]:
    current = load_json(MODEL_CONFIG) if MODEL_CONFIG.exists() else {"providers": []}
    by_id = {provider["id"]: provider for provider in current.get("providers", [])}
    for provider in req.providers:
        patch = provider.dict(exclude_none=True)
        by_id[provider.id] = {**by_id.get(provider.id, {}), **patch}
    next_config = {
        "schema_version": "nbot.model_providers.local.v1",
        "default_research_provider": req.default_research_provider or current.get("default_research_provider"),
        "providers": list(by_id.values()),
    }
    write_json(MODEL_CONFIG, next_config)
    return {
        "ok": True,
        "message": "Model provider settings saved locally for this PoC workspace.",
        "models": active_providers(),
    }


@app.get("/api/plan")
def plan() -> dict[str, Any]:
    return load_json(GRAPH)


@app.post("/api/calculate")
def calculate(req: CalculateRequest | None = None) -> dict[str, Any]:
    payload = {}
    if req:
        if req.vessel is not None:
            payload["vessel"] = req.vessel
        if req.rule_pack is not None:
            if not req.rule_pack.get("rules"):
                raise HTTPException(status_code=409, detail="No generated tariff rules are active. Upload or activate a generated rule pack before calculating.")
            payload["rule_pack"] = req.rule_pack
    if not payload.get("rule_pack") and not has_generated_rule_pack():
        raise HTTPException(status_code=409, detail="No generated rule pack is active. Upload a tariff document and generate rules, or submit rule_pack in the request.")
    return enrich_result(run_core("calculate", payload or None))


@app.post("/api/rule-pack/validate")
def validate_rule_pack(rule_pack: dict[str, Any]) -> dict[str, Any]:
    return run_core("validate-rule-pack", rule_pack)


@app.post("/api/rule-pack/activate")
def activate_rule_pack(req: ActivateRulePackRequest) -> dict[str, Any]:
    return store_generated_rule_pack(req.rule_pack, req.source_id)


@app.post("/api/document/upload")
async def upload_document(file: UploadFile = File(...)) -> dict[str, Any]:
    data = await file.read()
    pages = extract_text_from_upload(file.filename or "upload", data)
    document = store_document(file.filename or "upload", data, pages)
    candidates = document_tools().candidate_terms(pages)
    document_parse = document_tools().parse_tariff_document(pages)
    extraction_pages = document_parse.get("evidence_packet", {}).get("pages") or pages[:3]
    pdf_bytes = data if (file.filename or "").lower().endswith(".pdf") else None
    extraction = rule_extraction_agent().extract(
        file.filename or "upload",
        extraction_pages,
        candidates,
        pdf_bytes=pdf_bytes,
    )
    activated: dict[str, Any] | None = None
    refinement: dict[str, Any] | None = None
    if extraction.get("status") == "generated":
        try:
            activated = store_generated_rule_pack(extraction["rule_pack"], document["source_id"])
        except HTTPException as exc:
            extraction = {
                **extraction,
                "status": "validation_failed",
                "message": "LLM returned a rule pack, but core validation rejected it.",
                "validation_error": exc.detail,
            }
        else:
            diffs = run_self_tests(extraction["rule_pack"])
            refinement = {
                "self_tests_run": len(extraction["rule_pack"].get("self_tests") or []),
                "self_tests_failed": len(diffs),
                "diffs": diffs,
                "status": "passed" if not diffs else "refining",
            }
            if diffs:
                refined = rule_extraction_agent().refine(extraction["rule_pack"], diffs, pdf_bytes=pdf_bytes)
                refinement["refine_result"] = {
                    "status": refined.get("status"),
                    "message": refined.get("message"),
                    "provider": refined.get("provider"),
                }
                if refined.get("status") == "refined":
                    try:
                        activated = store_generated_rule_pack(refined["rule_pack"], document["source_id"])
                        post_diffs = run_self_tests(refined["rule_pack"])
                        refinement["post_refine_failed"] = len(post_diffs)
                        refinement["post_refine_diffs"] = post_diffs
                        refinement["status"] = "passed" if not post_diffs else "refined_partial"
                        extraction = {**extraction, "rule_pack": refined["rule_pack"], "input_mode": refined.get("input_mode", extraction.get("input_mode"))}
                    except HTTPException as exc:
                        refinement["status"] = "refine_validation_failed"
                        refinement["validation_error"] = exc.detail
    if extraction.get("status") == "failed":
        extraction = {
            **extraction,
            "research_required": research(
                ResearchRequest(
                    query="Resolve tariff rule extraction into executable independent charge rules or identify required core extensions.",
                    context={
                        "filename": file.filename,
                        "source_id": document["source_id"],
                        "failure": extraction.get("message"),
                        "document_parse": {
                            "document_terms": document_parse.get("document_terms", [])[:12],
                            "retrieved_chunks": document_parse.get("rag", {}).get("retrieved_chunks", [])[:8],
                        },
                    },
                )
            ),
        }
    return {
        "schema_version": "port_tariff.document_intake.v1",
        "source_id": document["source_id"],
        "filename": file.filename,
        "pages": len(pages),
        "candidate_terms": candidates,
        "document_parse": document_parse,
        "rule_generation": extraction,
        "refinement": refinement,
        "next_stage": "tool_ready" if activated else ("research_required" if extraction.get("status") == "failed" else "configure_llm_or_review_open_questions"),
        "compiled_tool_preview": activated["tools"]["tools"][0] if activated and activated["tools"].get("tools") else None,
        "rule_pack_required": activated is None,
        "activated_rule_pack": activated,
        "prompt": "prompts/rule_extraction_agent.md",
        "page_links": [
            {
                "label": f"Page {page['page']}",
                "url": f"/api/document/{document['source_id']}/page/{page['page']}",
            }
            for page in pages[:12]
        ],
        "page_text_preview": pages[:3],
        "known_ports": ports(),
    }


@app.get("/api/document/{source_id}/page/{page}", response_class=PlainTextResponse)
def document_page(source_id: str, page: int) -> str:
    if source_id == "generated":
        return "Generated rule pack evidence. Upload a tariff document to link evidence directly to extracted pages."
    try:
        return document_tools().page_text(source_id, page)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Document source not found")
    except KeyError:
        raise HTTPException(status_code=404, detail="Page not found")


def research_agent() -> ResearchAgent:
    """Build a ResearchAgent with raw provider config (keys intact) and prompt template."""
    prompt = (POC / "prompts" / "research_agent.md").read_text()
    return ResearchAgent(raw_provider_config(), prompt)


def attach_active_document_pages(context: dict[str, Any] | None) -> dict[str, Any]:
    """Augment a research context with page text from the active document, if any."""
    ctx = dict(context or {})
    if "pages" not in ctx:
        doc = active_document()
        if doc:
            ctx["pages"] = [
                {"page": page.get("page"), "text": page.get("text", "")[:4000]}
                for page in (doc.get("pages") or [])[:8]
            ]
    return ctx


@app.post("/api/research/clarify")
def research(req: ResearchRequest) -> dict[str, Any]:
    return research_agent().clarify(req.query, attach_active_document_pages(req.context))

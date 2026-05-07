from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


@contextlib.contextmanager
def _silenced_stderr():
    """Redirect fd 2 to /dev/null so C-extension stderr writes stay out of logs."""
    saved = os.dup(2)
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(saved)
        os.close(devnull)


def _probe_faiss():
    """Attempt to import faiss once at module load with stderr silenced.

    The numpy 2.x ABI break makes faiss-cpu's swig extension emit scary tracebacks
    even when the import would otherwise be caught. Probing here keeps logs clean
    and lets `_build_rag_index` skip the import attempt entirely when faiss is
    unusable in the current environment.
    """
    try:
        with _silenced_stderr():
            import faiss as module  # type: ignore
        return module
    except Exception:
        return None


_FAISS_MODULE = _probe_faiss()


class DocumentTools:
    """Document tools used by agents and API endpoints."""

    STOPWORDS: frozenset[str] = frozenset(
        {
            "about",
            "after",
            "also",
            "and",
            "are",
            "as",
            "been",
            "be",
            "but",
            "by",
            "can",
            "for",
            "from",
            "has",
            "have",
            "if",
            "in",
            "is",
            "into",
            "its",
            "may",
            "not",
            "of",
            "or",
            "per",
            "shall",
            "such",
            "that",
            "the",
            "their",
            "these",
            "this",
            "to",
            "under",
            "will",
            "with",
            "within",
        }
    )

    def __init__(self, runtime_dir: Path):
        self.runtime_dir = runtime_dir
        self.documents_dir = runtime_dir / "documents"

    def extract_pages(self, filename: str, data: bytes) -> list[dict[str, Any]]:
        """Extract page text from a PDF or text upload."""
        if filename.lower().endswith(".pdf"):
            from PyPDF2 import PdfReader

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp:
                temp.write(data)
                temp_path = Path(temp.name)
            try:
                reader = PdfReader(str(temp_path))
                return [
                    {"page": index + 1, "text": page.extract_text() or ""}
                    for index, page in enumerate(reader.pages)
                ]
            finally:
                temp_path.unlink(missing_ok=True)
        return [{"page": 1, "text": data.decode("utf-8", errors="ignore")}]

    def store(self, filename: str, data: bytes, pages: list[dict[str, Any]]) -> dict[str, Any]:
        """Persist extracted document pages and make this document active."""
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(data).hexdigest()[:16]
        doc = {
            "source_id": digest,
            "filename": filename,
            "pages": pages,
            "page_count": len(pages),
        }
        self._write_json(self.documents_dir / f"{digest}.json", doc)
        self._write_json(self.runtime_dir / "active_document.json", doc)
        return doc

    def list_documents(self) -> list[dict[str, Any]]:
        """Return all uploaded documents without loading large page text into the UI."""
        if not self.documents_dir.exists():
            return []
        documents: list[dict[str, Any]] = []
        for path in sorted(self.documents_dir.glob("*.json")):
            doc = self._load_json(path)
            documents.append(
                {
                    "source_id": doc.get("source_id"),
                    "filename": doc.get("filename"),
                    "page_count": doc.get("page_count", len(doc.get("pages", []))),
                }
            )
        return documents

    def active_document(self) -> dict[str, Any] | None:
        """Return the currently active uploaded document, if present."""
        path = self.runtime_dir / "active_document.json"
        return self._load_json(path) if path.exists() else None

    def page_text(self, source_id: str, page: int) -> str:
        """Return extracted text for a source page."""
        path = self.documents_dir / f"{source_id}.json"
        if not path.exists():
            raise FileNotFoundError("Document source not found")
        doc = self._load_json(path)
        for item in doc.get("pages", []):
            if item.get("page") == page:
                return item.get("text") or ""
        raise KeyError("Page not found")

    def candidate_terms(self, pages: list[dict[str, Any]]) -> list[dict[str, str]]:
        """Find document-derived signals before model-backed normalization."""
        return [
            {"term": term, "action": "retrieve local evidence chunks for rule_extraction_agent"}
            for term, _score in self._document_keyphrases(pages, limit=12)
        ]

    def parse_tariff_document(self, pages: list[dict[str, Any]], max_pages: int = 6, max_chars: int = 14000) -> dict[str, Any]:
        """Build a deterministic, model-sized evidence packet from extracted document pages."""
        document_terms = self._document_keyphrases(pages, limit=36)
        profiles = [self._profile_page(page, document_terms) for page in pages]
        ranked = sorted(profiles, key=lambda item: (-item["score"], item["page"]))
        rag_index = self._build_rag_index(pages)
        queries = self._derive_queries(pages, document_terms, profiles)
        retrieved = self._retrieve_rag_chunks(rag_index, queries, document_terms, top_k=28)
        packet_pages = self._packet_pages_from_chunks(retrieved, profiles, max_pages=max_pages, max_chars=max_chars)
        selected_pages = {item["page"] for item in packet_pages}
        return {
            "schema_version": "port_tariff.document_parse.v1",
            "page_count": len(pages),
            "document_terms": [{"term": term, "score": round(score, 3)} for term, score in document_terms[:18]],
            "rag": {
                "engine": rag_index["backend"],
                "backend_error": rag_index.get("backend_error"),
                "chunk_count": len(rag_index["chunks"]),
                "queries": queries,
                "retrieved_chunks": [
                    {
                        "chunk_id": chunk["chunk_id"],
                        "page": chunk["page"],
                        "score": round(chunk["score"], 3),
                        "query": chunk["query"],
                        "signals": chunk["signals"],
                    }
                    for chunk in retrieved[:16]
                ],
            },
            "ranked_pages": [
                {
                    "page": profile["page"],
                    "score": profile["score"],
                    "signals": profile["signals"],
                    "headings": profile["headings"][:4],
                    "chars": profile["chars"],
                    "selected": profile["page"] in selected_pages,
                }
                for profile in ranked[:12]
            ],
            "evidence_packet": {
                "page_count": len(packet_pages),
                "char_count": sum(len(page["text"]) for page in packet_pages),
                "pages": packet_pages,
            },
        }

    def _build_rag_index(self, pages: list[dict[str, Any]]) -> dict[str, Any]:
        """Build a local vector retrieval index over page chunks."""
        import numpy as np

        chunks: list[dict[str, Any]] = []
        vectors: list[Any] = []
        for page in pages:
            page_number = page.get("page")
            for offset, text in enumerate(self._chunk_text(page.get("text") or "")):
                tokens = self._tokens(text)
                if not tokens:
                    continue
                token_counts = Counter(tokens)
                lowered = text.lower()
                vector = self._embed_text(text)
                chunks.append(
                    {
                        "chunk_id": f"p{page_number}:c{offset + 1}",
                        "page": page_number,
                        "text": text,
                        "tokens": token_counts,
                        "length": len(tokens),
                        "signals": self._chunk_keyphrases(text, lowered),
                        "structure_score": self._structure_score(text),
                    }
                )
                vectors.append(vector)
        matrix = np.vstack(vectors).astype("float32") if vectors else np.zeros((0, 384), dtype="float32")
        backend = "numpy_hash_embeddings"
        backend_error = None if _FAISS_MODULE else "faiss unavailable in current env (numpy ABI mismatch); using numpy fallback"
        faiss_index = None
        if _FAISS_MODULE is not None and len(chunks):
            try:
                faiss_index = _FAISS_MODULE.IndexFlatIP(matrix.shape[1])
                faiss_index.add(matrix)
                backend = "faiss_hash_embeddings"
            except Exception as exc:
                backend_error = f"{type(exc).__name__}: {exc}"
        return {
            "chunks": chunks,
            "matrix": matrix,
            "faiss_index": faiss_index,
            "backend": backend,
            "backend_error": backend_error,
        }

    def _retrieve_rag_chunks(
        self,
        index: dict[str, Any],
        queries: list[str],
        document_terms: list[tuple[str, float]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Retrieve diverse evidence chunks with local vector search."""
        import numpy as np

        term_weights = dict(document_terms)
        seen: dict[str, dict[str, Any]] = {}
        for query in queries:
            query_vector = self._embed_text(query)
            candidate_scores = self._search_vectors(index, query_vector, top_k=top_k * 3)
            for chunk_index, similarity in candidate_scores:
                chunk = index["chunks"][chunk_index]
                score = similarity
                score += min(chunk.get("structure_score", 0.0), 40.0) * 0.01
                score += sum(term_weights.get(term, 0.0) for term in chunk["signals"]) * 0.03
                if score <= 0:
                    continue
                existing = seen.get(chunk["chunk_id"])
                if not existing or score > existing["score"]:
                    seen[chunk["chunk_id"]] = {
                        **chunk,
                        "score": score,
                        "query": query,
                    }
        ranked = sorted(seen.values(), key=lambda item: (-item["score"], item["page"], item["chunk_id"]))
        return self._diversify_chunks(ranked, top_k)

    def _search_vectors(self, index: dict[str, Any], query_vector: Any, top_k: int) -> list[tuple[int, float]]:
        """Search FAISS when available, otherwise use NumPy cosine similarity."""
        import numpy as np

        if not len(index["chunks"]):
            return []
        query = query_vector.astype("float32").reshape(1, -1)
        if index.get("faiss_index") is not None:
            scores, indices = index["faiss_index"].search(query, min(top_k, len(index["chunks"])))
            return [
                (int(idx), float(score))
                for idx, score in zip(indices[0], scores[0])
                if idx >= 0
            ]
        scores = index["matrix"] @ query_vector.astype("float32")
        order = np.argsort(-scores)[:top_k]
        return [(int(idx), float(scores[idx])) for idx in order]

    def _diversify_chunks(self, ranked: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
        """Prefer high-ranking chunks while avoiding one page monopolizing context."""
        selected: list[dict[str, Any]] = []
        per_page: defaultdict[int, int] = defaultdict(int)
        for chunk in ranked:
            if per_page[chunk["page"]] >= 4:
                continue
            selected.append(chunk)
            per_page[chunk["page"]] += 1
            if len(selected) >= top_k:
                break
        return selected

    def _packet_pages_from_chunks(
        self,
        chunks: list[dict[str, Any]],
        profiles: list[dict[str, Any]],
        max_pages: int,
        max_chars: int,
    ) -> list[dict[str, Any]]:
        """Group retrieved chunks into page-shaped packets for the extraction prompt."""
        profiles_by_page = {profile["page"]: profile for profile in profiles}
        grouped: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)
        for chunk in chunks:
            grouped[chunk["page"]].append(chunk)
        selected_pages: list[dict[str, Any]] = []
        chars = 0
        page_order = sorted(grouped, key=lambda page: (-max(chunk["score"] for chunk in grouped[page]), page))
        for page_number in page_order:
            if len(selected_pages) >= max_pages:
                break
            profile = profiles_by_page.get(page_number, {})
            blocks = []
            for chunk in sorted(grouped[page_number], key=lambda item: item["chunk_id"]):
                blocks.append(f"[{chunk['chunk_id']} score={chunk['score']:.2f}]\n{chunk['text']}")
            text = "\n\n".join(blocks)
            remaining = max_chars - chars
            if remaining <= 0:
                break
            text = text[:remaining]
            if not text.strip():
                continue
            selected_pages.append(
                {
                    "page": page_number,
                    "score": profile.get("score", 0),
                    "headings": profile.get("headings", []),
                    "signals": sorted({signal for chunk in grouped[page_number] for signal in chunk["signals"]}),
                    "snippets": profile.get("snippets", []),
                    "text": text,
                    "chunks": [
                        {
                            "chunk_id": chunk["chunk_id"],
                            "score": round(chunk["score"], 3),
                            "query": chunk["query"],
                        }
                        for chunk in grouped[page_number]
                    ],
                }
            )
            chars += len(text)
        return sorted(selected_pages, key=lambda item: item["page"])

    def _profile_page(self, page: dict[str, Any], document_terms: list[tuple[str, float]]) -> dict[str, Any]:
        """Score one page for extraction relevance using document-derived signals."""
        text = page.get("text") or ""
        lowered = text.lower()
        signals = [term for term, _score in document_terms if term in lowered]
        term_weights = dict(document_terms)
        score = sum(term_weights.get(term, 0.0) for term in signals)
        score += self._structure_score(text)
        if "contents" in lowered[:300]:
            score -= 10
        headings = self._extract_headings(text)
        snippets = self._extract_snippets(text, signals)
        return {
            "page": page.get("page"),
            "text": text,
            "chars": len(text),
            "score": max(score, 0),
            "signals": signals,
            "headings": headings,
            "snippets": snippets,
            "packet_char_limit": min(max(len(text), 0), 3500),
        }

    def _extract_headings(self, text: str) -> list[str]:
        """Extract visible section markers from OCR/page text."""
        headings: list[str] = []
        for raw in text.splitlines():
            line = " ".join(raw.split())
            if not line:
                continue
            if re.match(r"^([A-Z§][A-Z0-9§. -]{2,}|[0-9]+(?:\.[0-9]+)*\s+.+)$", line):
                headings.append(line[:180])
            elif len(line) < 120 and line.isupper():
                headings.append(line[:180])
            if len(headings) >= 8:
                break
        return headings

    def _document_keyphrases(self, pages: list[dict[str, Any]], limit: int) -> list[tuple[str, float]]:
        """Derive keyphrases from the uploaded document instead of static domain terms."""
        page_count = max(len(pages), 1)
        phrase_counts: Counter[str] = Counter()
        phrase_pages: defaultdict[str, set[int]] = defaultdict(set)
        for page in pages:
            page_number = page.get("page", 0)
            text = page.get("text") or ""
            for phrase in self._candidate_phrases(text):
                phrase_counts[phrase] += 1
                phrase_pages[phrase].add(page_number)
            for heading in self._extract_headings(text):
                for phrase in self._candidate_phrases(heading):
                    phrase_counts[phrase] += 3
                    phrase_pages[phrase].add(page_number)
        scored: list[tuple[str, float]] = []
        for phrase, count in phrase_counts.items():
            df = len(phrase_pages[phrase])
            if df / page_count > 0.45:
                continue
            if count < 2 and len(phrase.split()) == 1:
                continue
            idf = math.log(1 + page_count / max(df, 1))
            shape_bonus = 1.4 if len(phrase.split()) > 1 else 1.0
            scored.append((phrase, math.log(count + 1) * idf * shape_bonus))
        return sorted(scored, key=lambda item: (-item[1], item[0]))[:limit]

    def _derive_queries(
        self,
        pages: list[dict[str, Any]],
        document_terms: list[tuple[str, float]],
        profiles: list[dict[str, Any]],
    ) -> list[str]:
        """Create retrieval queries from headings and document keyphrases."""
        queries: list[str] = []
        top_terms = [term for term, _score in document_terms[:18]]
        if top_terms:
            for start in range(0, min(len(top_terms), 18), 6):
                queries.append(" ".join(top_terms[start:start + 6]))
        for page in pages[:3]:
            for heading in self._extract_headings(page.get("text") or "")[:6]:
                tokens = self._tokens(heading)
                if len(tokens) >= 2:
                    queries.append(" ".join(tokens[:10]))
        pages_by_number = {page.get("page"): page for page in pages}
        for profile in sorted(profiles, key=lambda item: (-self._structure_score(item["text"]), item["page"]))[:8]:
            page = pages_by_number.get(profile["page"], {})
            for heading in profile.get("headings", [])[:3]:
                queries.append(" ".join(self._tokens(heading)[:12]))
            for line in self._numeric_lines(page.get("text") or "")[:3]:
                queries.append(" ".join(self._tokens(line)[:16]))
        unique: list[str] = []
        seen: set[str] = set()
        for query in queries:
            normalized = " ".join(self._tokens(query))
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique.append(normalized)
        return unique[:8] or [" ".join(top_terms[:8])]

    def _chunk_keyphrases(self, text: str, lowered: str) -> list[str]:
        """Derive chunk-local signals from phrase shape and repetition."""
        phrases = self._candidate_phrases(text)
        counts = Counter(phrases)
        return [phrase for phrase, _count in counts.most_common(10) if phrase in lowered]

    def _candidate_phrases(self, text: str) -> list[str]:
        """Generate unsupervised lexical phrase candidates."""
        tokens = self._tokens(text)
        filtered = [token for token in tokens if len(token) >= 3 and token not in self.STOPWORDS and not token.isdigit()]
        phrases: list[str] = []
        phrases.extend(filtered)
        for size in (2, 3):
            for index in range(0, max(len(filtered) - size + 1, 0)):
                phrase = " ".join(filtered[index:index + size])
                if len(phrase) >= 6:
                    phrases.append(phrase)
        return phrases

    def _extract_snippets(self, text: str, signals: list[str]) -> list[dict[str, str]]:
        """Return short evidence snippets around relevant tariff terms."""
        snippets: list[dict[str, str]] = []
        lowered = text.lower()
        for term in signals[:8]:
            index = lowered.find(term)
            if index < 0:
                continue
            start = max(0, index - 220)
            end = min(len(text), index + 520)
            snippet = " ".join(text[start:end].split())
            snippets.append({"term": term, "text": snippet})
        return snippets

    def _chunk_text(self, text: str, chunk_chars: int = 1200, overlap: int = 180) -> list[str]:
        """Split page text into overlapping retrieval chunks."""
        normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if not normalized:
            return []
        chunks: list[str] = []
        start = 0
        while start < len(normalized):
            end = min(len(normalized), start + chunk_chars)
            if end < len(normalized):
                boundary = normalized.rfind("\n", start, end)
                if boundary > start + chunk_chars // 2:
                    end = boundary
            chunk = normalized[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(normalized):
                break
            start = max(end - overlap, start + 1)
        return chunks

    def _structure_score(self, text: str) -> float:
        """Score document structure without domain keywords."""
        lowered = text.lower()
        money_hits = len(re.findall(r"(?:€|eur|usd|zar|gbp|\$)\s*\d|\b\d+[.,]\d{2,4}\b", lowered))
        numeric_density = len(re.findall(r"\b\d+(?:[.,]\d+)?\b", text))
        table_like_lines = sum(1 for line in text.splitlines() if len(re.findall(r"\b\d+(?:[.,]\d+)?\b", line)) >= 3)
        operator_lines = sum(1 for line in text.splitlines() if re.search(r"[\u20ac$]|\b[x×]\b|%|=", line, flags=re.I))
        return min(money_hits * 2, 24) + min(numeric_density / 8, 16) + min(table_like_lines * 3, 24) + min(operator_lines, 16)

    def _numeric_lines(self, text: str) -> list[str]:
        """Return lines that look like tables, calculations, or examples."""
        lines: list[tuple[float, str]] = []
        for raw in text.splitlines():
            line = " ".join(raw.split())
            if not line:
                continue
            numbers = len(re.findall(r"\b\d+(?:[.,]\d+)?\b", line))
            money = len(re.findall(r"(?:€|eur|usd|zar|gbp|\$)\s*\d", line.lower()))
            operators = len(re.findall(r"[\u20ac$%]|\b[x×]\b|=", line, flags=re.I))
            score = numbers + money * 2 + operators
            if score >= 3:
                lines.append((score, line[:220]))
        return [line for _score, line in sorted(lines, key=lambda item: -item[0])]

    def _embed_text(self, text: str, dims: int = 384) -> Any:
        """Create a deterministic local hashed embedding vector."""
        import numpy as np

        vector = np.zeros(dims, dtype="float32")
        tokens = self._tokens(text)
        features = tokens[:]
        features.extend(" ".join(tokens[index:index + 2]) for index in range(max(len(tokens) - 1, 0)))
        features.extend(" ".join(tokens[index:index + 3]) for index in range(max(len(tokens) - 2, 0)))
        if not features:
            return vector
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "little") % dims
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector /= norm
        return vector

    def _tokens(self, text: str) -> list[str]:
        """Tokenize text for local lexical retrieval."""
        return [token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 1]

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2))

    def _load_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text())

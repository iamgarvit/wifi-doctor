"""Hybrid retrieval over the local knowledge base.

Two retrievers, fused:

* **BM25** (lexical). Wi-Fi logs are full of exact tokens -- ``status_code=17``,
  ``EAPOL-Key``, ``CTRL-EVENT-ASSOC-REJECT`` -- and a dense model happily maps
  status code 17 and status code 27 to near-identical vectors. Lexical search
  does not.
* **Local sentence embeddings** (semantic). The user's phrasing ("it keeps
  asking for the password again") shares no tokens with the document that
  answers it. Dense search does.

Neither alone is good enough, so results are fused with **Reciprocal Rank
Fusion**: ``score = sum over retrievers of 1/(k + rank)``. RRF needs no score
normalisation between two retrievers whose scores are on incomparable scales,
which is exactly the situation here.

Embeddings are optional at runtime. If ``sentence-transformers`` is missing, the
model cannot be downloaded, or ``WIFI_DOCTOR_EMBEDDINGS=0`` is set, the index
silently degrades to BM25-only and reports ``backend == "bm25"``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

log = logging.getLogger(__name__)

DEFAULT_KB_DIR = Path(__file__).resolve().parents[2] / "kb"
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "kb_index"
# bge-small-en-v1.5 is 133MB and CPU-fast; MiniLM is the smaller fallback.
EMBED_MODELS = ("BAAI/bge-small-en-v1.5", "sentence-transformers/all-MiniLM-L6-v2")
RRF_K = 60

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens, keeping underscores so ``status_code`` stays one token."""
    return _TOKEN_RE.findall(text.lower())


@dataclass(frozen=True)
class Chunk:
    doc_id: str  # filename stem -- this is what appears in kb_citations
    title: str  # the document's H1
    heading: str  # the section's H2, or "" for the preamble
    text: str

    @property
    def label(self) -> str:
        return f"{self.doc_id}#{self.heading}" if self.heading else self.doc_id


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float
    rank_bm25: int | None
    rank_dense: int | None

    def snippet(self, max_chars: int = 700) -> str:
        t = self.chunk.text.strip()
        return t if len(t) <= max_chars else t[: max_chars - 1].rstrip() + "…"


def load_chunks(kb_dir: Path = DEFAULT_KB_DIR) -> list[Chunk]:
    """Split every KB document into its H2 sections.

    Section-level chunks are the right granularity here: the documents are
    already short and each H2 answers one question, so a chunk is a
    self-contained answer rather than an arbitrary window.
    """
    chunks: list[Chunk] = []
    for path in sorted(kb_dir.glob("*.md")):
        raw = path.read_text()
        title_m = re.search(r"^#\s+(.+)$", raw, re.MULTILINE)
        title = title_m.group(1).strip() if title_m else path.stem
        body = raw[title_m.end() :] if title_m else raw
        parts = re.split(r"^##\s+(.+)$", body, flags=re.MULTILINE)
        preamble = parts[0].strip()
        if preamble:
            chunks.append(Chunk(path.stem, title, "", f"{title}\n\n{preamble}"))
        for heading, text in zip(parts[1::2], parts[2::2], strict=False):
            text = text.strip()
            if text:
                chunks.append(
                    Chunk(
                        path.stem, title, heading.strip(), f"{title} — {heading.strip()}\n\n{text}"
                    )
                )
    return chunks


def _embeddings_enabled() -> bool:
    return os.environ.get("WIFI_DOCTOR_EMBEDDINGS", "auto").lower() not in {"0", "false", "no"}


class KnowledgeBase:
    """BM25 + optional dense index over ``kb/``, with the dense half cached to disk."""

    def __init__(
        self,
        kb_dir: Path = DEFAULT_KB_DIR,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        *,
        use_embeddings: bool | None = None,
    ) -> None:
        self.kb_dir = Path(kb_dir)
        self.cache_dir = Path(cache_dir)
        self.chunks = load_chunks(self.kb_dir)
        if not self.chunks:
            raise ValueError(f"no knowledge-base documents found in {self.kb_dir}")
        self.bm25 = BM25Okapi([tokenize(c.text) for c in self.chunks])
        self._model = None
        self._matrix: np.ndarray | None = None
        self.model_name: str | None = None
        want = _embeddings_enabled() if use_embeddings is None else use_embeddings
        if want:
            self._build_dense()

    # -- dense half --------------------------------------------------------
    @property
    def backend(self) -> str:
        # Both halves are required: a cached matrix is useless without the
        # encoder that turns a query into a comparable vector.
        return "hybrid" if self._matrix is not None and self._model is not None else "bm25"

    def _fingerprint(self, model_name: str) -> str:
        h = hashlib.sha256(model_name.encode())
        for c in self.chunks:
            h.update(c.label.encode())
            h.update(c.text.encode())
        return h.hexdigest()[:16]

    def _build_dense(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:  # pragma: no cover - depends on the environment
            log.info("embeddings unavailable (%s); falling back to BM25-only", exc)
            return
        for name in EMBED_MODELS:
            try:
                fp = self._fingerprint(name)
                npy = self.cache_dir / f"{fp}.npy"
                meta = self.cache_dir / f"{fp}.json"
                if npy.exists() and meta.exists():
                    # Load the encoder first: if it fails we must fall through
                    # to the next model with no half-built index left behind.
                    model = SentenceTransformer(name, device="cpu")
                    self._matrix = np.load(npy)
                    self._model = model
                    self.model_name = json.loads(meta.read_text())["model"]
                    log.info("loaded cached dense index %s", npy.name)
                    return
                model = SentenceTransformer(name, device="cpu")
                vecs = model.encode(
                    [c.text for c in self.chunks],
                    normalize_embeddings=True,
                    show_progress_bar=False,
                    batch_size=16,
                )
                self._matrix = np.asarray(vecs, dtype=np.float32)
                self._model = model
                self.model_name = name
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                np.save(npy, self._matrix)
                meta.write_text(json.dumps({"model": name, "n_chunks": len(self.chunks)}))
                log.info("built dense index with %s", name)
                return
            except Exception as exc:  # pragma: no cover - network/model failures
                log.info("embedding model %s unavailable (%s)", name, exc)
                self._matrix, self._model, self.model_name = None, None, None
        log.info("no embedding model loaded; falling back to BM25-only")

    # -- search ------------------------------------------------------------
    def search(self, query: str, k: int = 4) -> list[Hit]:
        """Return the top ``k`` chunks for ``query``, fused across both retrievers."""
        if not query.strip():
            return []
        pool = min(len(self.chunks), max(k * 5, 20))

        bm_scores = self.bm25.get_scores(tokenize(query))
        bm_order = list(np.argsort(bm_scores)[::-1][:pool])
        ranks: dict[int, dict[str, int]] = {}
        for r, idx in enumerate(bm_order):
            ranks.setdefault(int(idx), {})["bm25"] = r

        if self._matrix is not None and self._model is not None:
            qv = self._model.encode([query], normalize_embeddings=True)[0]
            sims = self._matrix @ np.asarray(qv, dtype=np.float32)
            for r, idx in enumerate(np.argsort(sims)[::-1][:pool]):
                ranks.setdefault(int(idx), {})["dense"] = r

        fused = {idx: sum(1.0 / (RRF_K + r) for r in rr.values()) for idx, rr in ranks.items()}
        top = sorted(fused, key=lambda i: (-fused[i], self.chunks[i].label))[:k]
        return [
            Hit(self.chunks[i], round(fused[i], 6), ranks[i].get("bm25"), ranks[i].get("dense"))
            for i in top
        ]

    def doc_ids(self) -> set[str]:
        return {c.doc_id for c in self.chunks}


# --------------------------------------------------------------------------
# code lookup -- reads the markdown tables in the KB directly
# --------------------------------------------------------------------------

_TABLE_ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*$", re.MULTILINE)


def load_code_table(kind: str, kb_dir: Path = DEFAULT_KB_DIR) -> dict[int, str]:
    """Parse ``reason-codes.md`` / ``status-codes.md`` into ``{code: meaning}``.

    The KB markdown is the single source of truth -- there is no second copy of
    these tables in Python that could drift away from what the model is shown.
    """
    if kind not in {"reason", "status"}:
        raise ValueError("kind must be 'reason' or 'status'")
    path = Path(kb_dir) / f"{kind}-codes.md"
    return {int(c): m.strip() for c, m in _TABLE_ROW_RE.findall(path.read_text())}


_KB_SINGLETON: KnowledgeBase | None = None


def get_kb(**kwargs) -> KnowledgeBase:
    """Process-wide knowledge base. Building the dense index is not free."""
    global _KB_SINGLETON
    if _KB_SINGLETON is None:
        _KB_SINGLETON = KnowledgeBase(**kwargs)
    return _KB_SINGLETON

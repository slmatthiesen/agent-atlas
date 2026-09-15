"""Retrieval-augmented grounding over the Meridian SOP corpus.

Real Vertex AI embeddings (`text-embedding-005`) and real Gemini generation. The
vector index is held in memory and searched by exact cosine similarity, which is
appropriate at this corpus size and keeps `docker compose up` free of an hour-long
index deployment. Swapping in a deployed Vertex AI Vector Search index means
replacing `VectorIndex.search` — the embedding and grounding paths are unchanged.
"""
import hashlib
import json
import math
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

from gcp_auth import PROJECT_ID, REGION, get_access_token

sys.stdout.reconfigure(encoding="utf-8")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-005")
GROUNDING_MODEL = os.getenv("GROUNDING_MODEL", "gemini-2.5-flash")
CORPUS_DIR = pathlib.Path(__file__).parent / "corpus"
CACHE_DIR = pathlib.Path(__file__).parent / ".rag_cache"
TOP_K = 3

_VERTEX_BASE = f"https://{REGION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{REGION}/publishers/google/models"

# Gemini 2.5 spends thinking tokens from the maxOutputTokens budget and bills them at
# the output rate. Grounded extraction needs none, but gemini-2.5-pro rejects a budget
# of 0 outright ("model does not support setting thinking_budget to 0"), so it gets its
# documented floor instead.
_MIN_THINKING_BUDGET = {"gemini-2.5-pro": 128}


def thinking_budget_for(model: str) -> int:
    return _MIN_THINKING_BUDGET.get(model, 0)


def _post(url: str, body: dict, timeout: int = 60) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {get_access_token()}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def embed(texts: list[str], task_type: str) -> list[list[float]]:
    """Embed texts in one batched call.

    `task_type` matters: documents and queries are embedded into different regions
    of the space, so using RETRIEVAL_DOCUMENT for both measurably degrades recall.
    """
    payload = {"instances": [{"content": t, "task_type": task_type} for t in texts]}
    response = _post(f"{_VERTEX_BASE}/{EMBEDDING_MODEL}:predict", payload)
    return [p["embeddings"]["values"] for p in response["predictions"]]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def chunk_markdown(path: pathlib.Path) -> list[dict]:
    """Split a SOP into one chunk per `##` section, keeping the heading as context."""
    raw = path.read_text(encoding="utf-8")
    title_match = re.search(r"^#\s+(.+)$", raw, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else path.stem

    chunks = []
    for index, section in enumerate(re.split(r"\n(?=##\s)", raw)):
        section = section.strip()
        if not section.startswith("##"):
            continue
        heading = section.splitlines()[0].lstrip("# ").strip()
        body = " ".join(line.strip() for line in section.splitlines()[1:] if line.strip())
        body = re.sub(r"\s+", " ", body)
        if not body:
            continue
        chunks.append({
            "chunk_id": f"{path.stem}-{index:02d}",
            "document_id": path.name,
            "document_title": title,
            "section": heading,
            "text": body,
        })
    return chunks


class VectorIndex:
    """In-memory vector index over the SOP corpus, with an on-disk embedding cache."""

    def __init__(self):
        self.chunks: list[dict] = []
        self.vectors: list[list[float]] = []
        self.built = False
        self.build_error: str | None = None

    def _cache_path(self, chunks: list[dict]) -> pathlib.Path:
        digest = hashlib.sha256(
            (EMBEDDING_MODEL + "|" + "|".join(c["chunk_id"] + c["text"] for c in chunks)).encode()
        ).hexdigest()[:16]
        return CACHE_DIR / f"embeddings-{digest}.json"

    def build(self) -> None:
        """Chunk the corpus and embed it, reusing the cache when the corpus is unchanged."""
        if self.built:
            return

        chunks = []
        for path in sorted(CORPUS_DIR.glob("*.md")):
            chunks.extend(chunk_markdown(path))
        if not chunks:
            self.build_error = f"No corpus documents found in {CORPUS_DIR}"
            return

        cache_file = self._cache_path(chunks)
        if cache_file.exists():
            self.vectors = json.loads(cache_file.read_text(encoding="utf-8"))
            self.chunks = chunks
            self.built = True
            return

        try:
            self.vectors = embed([f"{c['document_title']} — {c['section']}. {c['text']}" for c in chunks],
                                 task_type="RETRIEVAL_DOCUMENT")
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, KeyError) as exc:
            detail = exc.read().decode("utf-8")[:200] if isinstance(exc, urllib.error.HTTPError) else str(exc)[:200]
            self.build_error = f"Embedding call failed: {detail}"
            return

        self.chunks = chunks
        CACHE_DIR.mkdir(exist_ok=True)
        cache_file.write_text(json.dumps(self.vectors), encoding="utf-8")
        self.built = True

    def search(self, query: str, top_k: int = TOP_K) -> list[dict]:
        self.build()
        if not self.built:
            raise RuntimeError(self.build_error or "Vector index unavailable")

        query_vector = embed([query], task_type="RETRIEVAL_QUERY")[0]
        scored = [
            {**chunk, "score": round(cosine(query_vector, vector), 4)}
            for chunk, vector in zip(self.chunks, self.vectors)
        ]
        scored.sort(key=lambda c: c["score"], reverse=True)
        return scored[:top_k]


INDEX = VectorIndex()

_GROUNDING_INSTRUCTION = """You answer questions for a clinical supply operations team.

Answer using ONLY the numbered context passages below. Cite the passages you use as
[1], [2] and so on. If the passages do not contain the answer, say so plainly rather
than drawing on outside knowledge. Be concise — three sentences at most.

Context passages:
{context}

Question: {question}"""


def grounded_answer(query: str, top_k: int = TOP_K) -> dict:
    """Retrieve the most relevant SOP passages and answer strictly from them."""
    started = time.perf_counter()
    retrieved = INDEX.search(query, top_k=top_k)

    context = "\n\n".join(
        f"[{i}] ({c['document_title']} — {c['section']}) {c['text']}"
        for i, c in enumerate(retrieved, start=1)
    )
    prompt = _GROUNDING_INSTRUCTION.format(context=context, question=query)

    # Leaving thinking enabled truncated answers mid-sentence at MAX_TOKENS, because
    # thinking drew down the same 400-token budget the answer needed.
    response = _post(
        f"{_VERTEX_BASE}/{GROUNDING_MODEL}:generateContent",
        {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 800,
                "thinkingConfig": {"thinkingBudget": thinking_budget_for(GROUNDING_MODEL)},
            },
        },
    )

    candidate = response["candidates"][0]
    answer = "".join(
        part.get("text", "")
        for part in candidate["content"].get("parts", [])
    ).strip()
    usage = response.get("usageMetadata", {})

    return {
        "status": "GROUNDED_SUCCESS",
        "query": query,
        "grounded_answer": answer,
        "retrieved_chunks": [
            {
                "chunk_id": c["chunk_id"],
                "document_id": c["document_id"],
                "document_title": c["document_title"],
                "section": c["section"],
                "text": c["text"][:400] + ("…" if len(c["text"]) > 400 else ""),
                "score": c["score"],
            }
            for c in retrieved
        ],
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimensions": len(INDEX.vectors[0]) if INDEX.vectors else None,
        "grounding_model": GROUNDING_MODEL,
        "indexed_chunks": len(INDEX.chunks),
        "retrieval": "exact cosine over in-memory index",
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "prompt_tokens": usage.get("promptTokenCount"),
        "output_tokens": usage.get("candidatesTokenCount"),
        "thinking_tokens": usage.get("thoughtsTokenCount", 0),
        "finish_reason": candidate.get("finishReason"),
    }


def corpus_summary() -> dict:
    """Describe the indexed corpus for the console's knowledge-base panel."""
    INDEX.build()
    documents: dict[str, dict] = {}
    for chunk in INDEX.chunks:
        entry = documents.setdefault(chunk["document_id"], {
            "document_id": chunk["document_id"],
            "title": chunk["document_title"],
            "chunks": 0,
            "sections": [],
        })
        entry["chunks"] += 1
        entry["sections"].append(chunk["section"])
    return {
        "documents": list(documents.values()),
        "total_chunks": len(INDEX.chunks),
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimensions": len(INDEX.vectors[0]) if INDEX.vectors else None,
        "index_ready": INDEX.built,
        "error": INDEX.build_error,
    }


if __name__ == "__main__":
    print("=== Building vector index over SOP corpus ===")
    INDEX.build()
    print(f"Indexed {len(INDEX.chunks)} chunks | model={EMBEDDING_MODEL} "
          f"| dims={len(INDEX.vectors[0]) if INDEX.vectors else 'n/a'}")
    if INDEX.build_error:
        print(f"ERROR: {INDEX.build_error}")
        raise SystemExit(1)

    for question in [
        "What temperature must Insulin Glargine be stored at?",
        "What happens if a clinic's DEA license has expired?",
        "How long can a temperature excursion last before the lot is quarantined?",
        "Who is the contracted carrier for refrigerated biologics?",
    ]:
        result = grounded_answer(question)
        print(f"\nQ: {question}")
        print(f"A: {result['grounded_answer']}")
        print(f"   retrieved: {[(c['section'], c['score']) for c in result['retrieved_chunks']]}")
        print(f"   {result['latency_ms']}ms | {result['prompt_tokens']}in/{result['output_tokens']}out tokens")

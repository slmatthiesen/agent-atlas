"""Measures accuracy, latency and real token cost per model tier.

Every number the dashboard and README publish comes from this harness. Grading is
deterministic, so a rerun reproduces the figures. Results land in
`evals/results/latest.json`, which the backend serves to the console.
"""
import argparse
import json
import pathlib
import statistics
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from gcp_auth import PROJECT_ID, REGION, get_access_token  # noqa: E402
from rag_engine import thinking_budget_for  # noqa: E402
from dataset import CATALOG, CLINICS, INTENT_EXTRACTION, LICENSE_GATE, RAG_GROUNDING  # noqa: E402

RESULTS_DIR = pathlib.Path(__file__).parent / "results"
VERTEX_BASE = (
    f"https://{REGION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}"
    f"/locations/{REGION}/publishers/google/models"
)

# Published Vertex AI list price, USD per 1M tokens, captured 2026-08-13.
# Thinking tokens bill at the output rate, which is why they are tracked separately.
# Verify against https://cloud.google.com/vertex-ai/generative-ai/pricing before
# quoting these figures anywhere that matters.
PRICING = {
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
}
PRICING_SOURCE = "https://cloud.google.com/vertex-ai/generative-ai/pricing"
PRICING_CAPTURED = "2026-08-13"

MODELS = list(PRICING.keys())


def generate(model: str, prompt: str, response_schema: dict | None = None,
             max_output_tokens: int = 512) -> dict:
    """One generateContent call, returning text plus real usage and latency."""
    config = {
        "temperature": 0.0,
        "maxOutputTokens": max_output_tokens,
        "thinkingConfig": {"thinkingBudget": thinking_budget_for(model)},
    }
    if response_schema:
        config["responseMimeType"] = "application/json"
        config["responseSchema"] = response_schema

    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": config}
    request = urllib.request.Request(
        f"{VERTEX_BASE}/{model}:generateContent",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {get_access_token()}", "Content-Type": "application/json"},
    )

    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"error": exc.read().decode("utf-8")[:300],
                "latency_ms": round((time.perf_counter() - started) * 1000, 1)}
    latency_ms = round((time.perf_counter() - started) * 1000, 1)

    candidate = payload["candidates"][0]
    text = "".join(p.get("text", "") for p in candidate["content"].get("parts", [])).strip()
    usage = payload.get("usageMetadata", {})
    return {
        "text": text,
        "latency_ms": latency_ms,
        "input_tokens": usage.get("promptTokenCount", 0),
        "output_tokens": usage.get("candidatesTokenCount", 0),
        "thinking_tokens": usage.get("thoughtsTokenCount", 0),
        "finish_reason": candidate.get("finishReason"),
    }


def cost_usd(model: str, input_tokens: int, output_tokens: int, thinking_tokens: int) -> float:
    price = PRICING[model]
    billable_output = output_tokens + thinking_tokens
    return (input_tokens / 1_000_000) * price["input"] + (billable_output / 1_000_000) * price["output"]


# ---------------------------------------------------------------------------
# Task runners
# ---------------------------------------------------------------------------
_CATALOG_BLOCK = "\n".join(f"  {sku}: {meta['name']}" for sku, meta in CATALOG.items())
_CLINIC_BLOCK = "\n".join(f"  {cid}: {meta['name']}" for cid, meta in CLINICS.items())

INTENT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "clinic_id": {"type": "STRING"},
        "sku": {"type": "STRING"},
        "quantity": {"type": "INTEGER"},
    },
    "required": ["clinic_id", "sku", "quantity"],
}

INTENT_PROMPT = """Extract the order intent from a clinic's spoken request.

Known catalog SKUs:
{catalog}

Known clinics:
{clinics}

Rules:
- Map the spoken product to exactly one catalog SKU.
- Map the spoken clinic to exactly one clinic ID.
- If the caller corrects themselves, use their final stated quantity.
- If no quantity is stated at all, use 1.
- Numbers may be spoken as words or digits, and a clinic number may be spoken digit by digit.

Spoken request: "{utterance}"
"""

GATE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"decision": {"type": "STRING", "enum": ["APPROVE", "REJECT"]}},
    "required": ["decision"],
}

GATE_PROMPT = """Decide whether this order may proceed to the warehouse.

Rule: an order for a RESTRICTED product may proceed only if the clinic's license_status
is ACTIVE and licensed_for_restricted_items is true. Non-restricted products may always
proceed.

Product: {sku} ({sku_name}), restricted={restricted}
Clinic: {clinic_id} ({clinic_name}), license_status={license_status}, licensed_for_restricted_items={licensed}

Answer APPROVE or REJECT.
"""


def run_intent_extraction(model: str) -> list[dict]:
    records = []
    for case in INTENT_EXTRACTION:
        prompt = INTENT_PROMPT.format(catalog=_CATALOG_BLOCK, clinics=_CLINIC_BLOCK,
                                      utterance=case["utterance"])
        result = generate(model, prompt, response_schema=INTENT_SCHEMA, max_output_tokens=256)
        passed, detail = False, result.get("error", "")
        if "text" in result:
            try:
                parsed = json.loads(result["text"])
                passed = all(parsed.get(k) == v for k, v in case["expected"].items())
                detail = json.dumps(parsed)
            except json.JSONDecodeError:
                detail = f"unparseable: {result['text'][:80]}"
        records.append({"case_id": case["id"], "passed": passed, "detail": detail, **result})
    return records


def run_license_gate(model: str) -> list[dict]:
    records = []
    for case in LICENSE_GATE:
        sku_meta, clinic_meta = CATALOG[case["sku"]], CLINICS[case["clinic_id"]]
        prompt = GATE_PROMPT.format(
            sku=case["sku"], sku_name=sku_meta["name"], restricted=sku_meta["restricted"],
            clinic_id=case["clinic_id"], clinic_name=clinic_meta["name"],
            license_status=clinic_meta["license_status"],
            licensed=clinic_meta["licensed_for_restricted_items"],
        )
        result = generate(model, prompt, response_schema=GATE_SCHEMA, max_output_tokens=128)
        passed, detail = False, result.get("error", "")
        if "text" in result:
            try:
                parsed = json.loads(result["text"])
                passed = parsed.get("decision") == case["expected"]
                detail = parsed.get("decision", "")
            except json.JSONDecodeError:
                detail = f"unparseable: {result['text'][:80]}"
        records.append({"case_id": case["id"], "passed": passed, "detail": detail, **result})
    return records


def run_rag_grounding(model: str) -> list[dict]:
    """Grounded answering against the live vector index, with this model generating."""
    import rag_engine

    original_model = rag_engine.GROUNDING_MODEL
    rag_engine.GROUNDING_MODEL = model
    records = []
    try:
        for case in RAG_GROUNDING:
            started = time.perf_counter()
            try:
                result = rag_engine.grounded_answer(case["question"])
            except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError, KeyError) as exc:
                records.append({"case_id": case["id"], "passed": False,
                                "detail": f"error: {str(exc)[:120]}",
                                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                                "input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0})
                continue

            answer = result["grounded_answer"].lower()
            has_required = all(any(v in answer for v in group) for group in case["must_include"])
            has_forbidden = any(bad in answer for bad in case["must_not_include"])
            records.append({
                "case_id": case["id"],
                "passed": has_required and not has_forbidden,
                "detail": result["grounded_answer"][:160],
                "latency_ms": result["latency_ms"],
                "input_tokens": result.get("prompt_tokens") or 0,
                "output_tokens": result.get("output_tokens") or 0,
                "thinking_tokens": result.get("thinking_tokens") or 0,
            })
    finally:
        rag_engine.GROUNDING_MODEL = original_model
    return records


TASKS = {
    "intent_extraction": (run_intent_extraction, len(INTENT_EXTRACTION),
                          "Spoken order to structured intent (voice-frontdoor)"),
    "license_gate": (run_license_gate, len(LICENSE_GATE),
                     "Restricted-product license decision (verification-agent)"),
    "rag_grounding": (run_rag_grounding, len(RAG_GROUNDING),
                      "Grounded answering over the SOP corpus (RAG)"),
}


def summarize(model: str, records: list[dict]) -> dict:
    latencies = [r["latency_ms"] for r in records if r.get("latency_ms")]
    total_in = sum(r.get("input_tokens", 0) for r in records)
    total_out = sum(r.get("output_tokens", 0) for r in records)
    total_think = sum(r.get("thinking_tokens", 0) for r in records)
    passed = sum(1 for r in records if r["passed"])
    n = len(records)
    total_cost = cost_usd(model, total_in, total_out, total_think)
    return {
        "cases": n,
        "passed": passed,
        "accuracy_pct": round(100 * passed / n, 1) if n else 0.0,
        "p50_latency_ms": round(statistics.median(latencies), 1) if latencies else None,
        "p95_latency_ms": round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 1) if len(latencies) > 1 else None,
        "mean_input_tokens": round(total_in / n, 1) if n else 0,
        "mean_output_tokens": round(total_out / n, 1) if n else 0,
        "mean_thinking_tokens": round(total_think / n, 1) if n else 0,
        "cost_per_1k_requests_usd": round(total_cost / n * 1000, 4) if n else 0.0,
        "failed_cases": [r["case_id"] for r in records if not r["passed"]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Meridian model eval suite.")
    parser.add_argument("--models", nargs="*", default=MODELS)
    parser.add_argument("--tasks", nargs="*", default=list(TASKS))
    args = parser.parse_args()

    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    results: dict[str, dict] = {}

    for task_name in args.tasks:
        runner, case_count, description = TASKS[task_name]
        results[task_name] = {"description": description, "cases": case_count, "models": {}}
        print(f"\n=== {task_name} ({case_count} cases) ===")
        for model in args.models:
            records = runner(model)
            summary = summarize(model, records)
            results[task_name]["models"][model] = {**summary, "records": records}
            print(f"  {model:24} {summary['accuracy_pct']:5.1f}%  "
                  f"p50 {summary['p50_latency_ms']:>7}ms  "
                  f"${summary['cost_per_1k_requests_usd']:.4f}/1k req"
                  + (f"  misses: {','.join(summary['failed_cases'])}" if summary["failed_cases"] else ""))

    payload = {
        "generated_at": started_at,
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "project_id": PROJECT_ID,
        "region": REGION,
        "pricing_usd_per_1m_tokens": PRICING,
        "pricing_source": PRICING_SOURCE,
        "pricing_captured": PRICING_CAPTURED,
        "grading": "deterministic (exact field match / required substrings) — no LLM judge",
        "thinking_budgets": {m: thinking_budget_for(m) for m in args.models},
        "tasks": results,
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote {RESULTS_DIR / 'latest.json'}")


if __name__ == "__main__":
    main()

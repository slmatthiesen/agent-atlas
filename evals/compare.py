"""Compare an eval run against the blessed baseline.

Pure functions over two result payloads — no network, no filesystem, no clock — so
the gate's own logic is unit-testable without spending a cent on Vertex.

The comparison is a set difference on case IDs, not a delta on an accuracy score.
With 26 cases, one case flipping pass->fail while another flips fail->pass leaves
the percentage identical: a real regression under a green dashboard. Cost and
latency are graded too, because a prompt change that holds accuracy and doubles
spend is also a regression, just a slower-burning one.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Fractional tolerance before a slower or pricier run counts as a regression.
# Generous on purpose: model-side variance is real, and a gate that cries wolf
# gets muted, which is worse than no gate because it reads as assurance.
DEFAULT_LATENCY_TOLERANCE = 0.30
DEFAULT_COST_TOLERANCE = 0.15


@dataclass
class SliceDelta:
    """One (task, model) pair's movement between baseline and current."""

    task: str
    model: str
    regressed: list[str] = field(default_factory=list)
    improved: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    latency_change: float | None = None
    cost_change: float | None = None
    latency_regressed: bool = False
    cost_regressed: bool = False

    @property
    def failed(self) -> bool:
        return bool(self.regressed or self.latency_regressed or self.cost_regressed)

    @property
    def quiet(self) -> bool:
        """Nothing moved at all — worth saying so explicitly in the report."""
        return not (
            self.regressed
            or self.improved
            or self.added
            or self.removed
            or self.latency_regressed
            or self.cost_regressed
        )


@dataclass
class Comparison:
    slices: list[SliceDelta]
    missing_slices: list[tuple[str, str]] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(s.failed for s in self.slices) or bool(self.missing_slices)

    @property
    def regressed_cases(self) -> list[str]:
        return [case for s in self.slices for case in s.regressed]


def case_outcomes(slice_payload: dict) -> dict[str, bool]:
    """case_id -> passed, from one (task, model) entry's records."""
    return {r["case_id"]: bool(r["passed"]) for r in slice_payload.get("records", [])}


def _relative_change(before: float | None, after: float | None) -> float | None:
    """Fractional change, or None when either side is missing or the base is zero."""
    if before is None or after is None or before == 0:
        return None
    return (after - before) / before


def compare(
    baseline: dict,
    current: dict,
    latency_tolerance: float = DEFAULT_LATENCY_TOLERANCE,
    cost_tolerance: float = DEFAULT_COST_TOLERANCE,
) -> Comparison:
    """Diff two run payloads (the shape run_eval.py writes to results/latest.json).

    A (task, model) slice present in the baseline but absent from the current run is
    reported as missing rather than silently passing — dropping a task is exactly how
    a suite quietly stops covering anything.

    Models the current run never touched are out of scope, not missing: CI gates on the
    cheap tier alone, and a narrow run must not fail for being narrow.
    """
    slices: list[SliceDelta] = []
    missing: list[tuple[str, str]] = []
    models_in_scope = {
        model
        for task in current.get("tasks", {}).values()
        for model in task.get("models", {})
    }

    for task, base_task in baseline.get("tasks", {}).items():
        cur_task = current.get("tasks", {}).get(task)
        for model, base_slice in base_task.get("models", {}).items():
            if model not in models_in_scope:
                continue
            cur_slice = (cur_task or {}).get("models", {}).get(model)
            if cur_slice is None:
                missing.append((task, model))
                continue

            before = case_outcomes(base_slice)
            after = case_outcomes(cur_slice)

            delta = SliceDelta(task=task, model=model)
            for case_id, was_passing in before.items():
                if case_id not in after:
                    delta.removed.append(case_id)
                elif was_passing and not after[case_id]:
                    delta.regressed.append(case_id)
                elif not was_passing and after[case_id]:
                    delta.improved.append(case_id)
            delta.added = [c for c in after if c not in before]

            delta.latency_change = _relative_change(
                base_slice.get("p50_latency_ms"), cur_slice.get("p50_latency_ms")
            )
            delta.cost_change = _relative_change(
                base_slice.get("cost_per_1k_requests_usd"),
                cur_slice.get("cost_per_1k_requests_usd"),
            )
            delta.latency_regressed = (
                delta.latency_change is not None and delta.latency_change > latency_tolerance
            )
            delta.cost_regressed = (
                delta.cost_change is not None and delta.cost_change > cost_tolerance
            )

            for bucket in (delta.regressed, delta.improved, delta.added, delta.removed):
                bucket.sort()
            slices.append(delta)

    return Comparison(slices=slices, missing_slices=missing)


def format_report(comparison: Comparison, baseline_blessed_at: str | None = None) -> str:
    """Human-readable gate output — this is what CI prints and what a reviewer reads."""
    lines = [
        f"=== regression check vs baseline"
        + (f" (blessed {baseline_blessed_at})" if baseline_blessed_at else "")
        + " ==="
    ]

    for s in comparison.slices:
        header = f"  {s.task} / {s.model}"
        if s.quiet:
            lines.append(f"{header}  no change")
            continue
        lines.append(header)
        for case_id in s.regressed:
            lines.append(f"    x REGRESSED  {case_id}   passed -> failed")
        for case_id in s.improved:
            lines.append(f"    + improved   {case_id}   failed -> passed")
        for case_id in s.added:
            lines.append(f"    . new case   {case_id}")
        for case_id in s.removed:
            lines.append(f"    - dropped    {case_id}")
        if s.latency_change is not None and s.latency_regressed:
            lines.append(f"    ! latency   {s.latency_change:+.0%}  (tolerance {DEFAULT_LATENCY_TOLERANCE:.0%})")
        if s.cost_change is not None and s.cost_regressed:
            lines.append(f"    ! cost      {s.cost_change:+.0%}  (tolerance {DEFAULT_COST_TOLERANCE:.0%})")

    for task, model in comparison.missing_slices:
        lines.append(f"  x MISSING    {task} / {model} is in the baseline but not this run")

    if comparison.failed:
        lines.append("")
        lines.append("FAIL — behavior moved against the baseline.")
        lines.append("If the change is intentional, re-bless with: python evals/run_eval.py --promote")
    else:
        lines.append("")
        lines.append("PASS — no regressions against the baseline.")
    return "\n".join(lines)

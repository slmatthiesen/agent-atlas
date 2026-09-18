"""Unit tests for the regression comparator.

Runs offline against synthetic payloads — no Vertex calls, no credentials, no spend.
That is the point of keeping compare.py pure: the thing that decides whether a change
ships is itself cheap to test.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from compare import compare, format_report  # noqa: E402


def payload(cases: dict[str, bool], p50: float = 100.0, cost: float = 0.01) -> dict:
    """One task / one model run payload in the shape run_eval.py writes."""
    return {
        "tasks": {
            "intent_extraction": {
                "models": {
                    "gemini-2.5-flash-lite": {
                        "p50_latency_ms": p50,
                        "cost_per_1k_requests_usd": cost,
                        "records": [
                            {"case_id": cid, "passed": ok} for cid, ok in cases.items()
                        ],
                    }
                }
            }
        }
    }


def test_identical_runs_pass():
    base = payload({"intent-01": True, "intent-02": True})
    result = compare(base, payload({"intent-01": True, "intent-02": True}))
    assert not result.failed
    assert result.slices[0].quiet


def test_flip_to_failing_is_a_regression():
    base = payload({"intent-01": True, "intent-02": True})
    result = compare(base, payload({"intent-01": True, "intent-02": False}))
    assert result.failed
    assert result.regressed_cases == ["intent-02"]


def test_offsetting_flips_still_fail():
    """The case this whole gate exists for: accuracy is unchanged, behavior is not."""
    base = payload({"intent-01": True, "intent-02": False})
    result = compare(base, payload({"intent-01": False, "intent-02": True}))
    assert result.failed
    assert result.regressed_cases == ["intent-01"]
    assert result.slices[0].improved == ["intent-02"]


def test_improvement_alone_does_not_fail():
    base = payload({"intent-01": False})
    result = compare(base, payload({"intent-01": True}))
    assert not result.failed
    assert result.slices[0].improved == ["intent-01"]


def test_cost_regression_fails_even_when_accuracy_holds():
    base = payload({"intent-01": True}, cost=0.010)
    result = compare(base, payload({"intent-01": True}, cost=0.020))
    assert result.failed
    assert result.slices[0].cost_regressed


def test_small_cost_move_is_within_tolerance():
    base = payload({"intent-01": True}, cost=0.010)
    result = compare(base, payload({"intent-01": True}, cost=0.0105))
    assert not result.failed


def test_latency_regression_fails():
    base = payload({"intent-01": True}, p50=100.0)
    result = compare(base, payload({"intent-01": True}, p50=200.0))
    assert result.failed
    assert result.slices[0].latency_regressed


def test_getting_faster_and_cheaper_never_fails():
    base = payload({"intent-01": True}, p50=200.0, cost=0.02)
    result = compare(base, payload({"intent-01": True}, p50=100.0, cost=0.01))
    assert not result.failed


def test_new_case_is_reported_but_does_not_fail():
    base = payload({"intent-01": True})
    result = compare(base, payload({"intent-01": True, "intent-02": False}))
    assert not result.failed
    assert result.slices[0].added == ["intent-02"]


def test_dropped_case_fails():
    """Deleting a failing case is the cheapest way to fake a green suite."""
    base = payload({"intent-01": True, "intent-02": True})
    result = compare(base, payload({"intent-01": True}))
    assert result.slices[0].removed == ["intent-02"]


def test_missing_slice_fails_rather_than_passing_silently():
    """A task present in the baseline but dropped from a run of the same model."""
    base = payload({"intent-01": True})
    current = payload({"intent-01": True})
    current["tasks"]["license_gate"] = current["tasks"].pop("intent_extraction")
    base["tasks"]["license_gate"] = {
        "models": {"gemini-2.5-flash-lite": {"records": [{"case_id": "gate-01", "passed": True}]}}
    }
    result = compare(base, current)
    assert result.failed
    assert ("intent_extraction", "gemini-2.5-flash-lite") in result.missing_slices


def test_narrow_run_does_not_fail_for_models_it_never_ran():
    """CI gates on the cheap tier; the other tiers are out of scope, not missing."""
    base = payload({"intent-01": True})
    base["tasks"]["intent_extraction"]["models"]["gemini-2.5-pro"] = {
        "records": [{"case_id": "intent-01", "passed": True}]
    }
    result = compare(base, payload({"intent-01": True}))
    assert not result.failed
    assert result.missing_slices == []
    assert [s.model for s in result.slices] == ["gemini-2.5-flash-lite"]


def test_zero_baseline_cost_does_not_divide_by_zero():
    base = payload({"intent-01": True}, cost=0.0)
    result = compare(base, payload({"intent-01": True}, cost=0.01))
    assert result.slices[0].cost_change is None
    assert not result.failed


def test_report_names_the_regressed_case():
    base = payload({"intent-01": True})
    text = format_report(compare(base, payload({"intent-01": False})), "2026-09-15")
    assert "intent-01" in text
    assert "REGRESSED" in text
    assert "FAIL" in text
    assert "2026-09-15" in text


def test_report_says_pass_when_clean():
    base = payload({"intent-01": True})
    text = format_report(compare(base, payload({"intent-01": True})))
    assert "PASS" in text
    assert "no change" in text

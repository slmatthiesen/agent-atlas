# Agent Atlas

**Discover, govern, and visualize your Google Cloud agents with Antigravity (AGY).**

Agent Atlas is a working reference and dashboard generator for multi-agent systems on GCP where **identity, not prompt engineering, is the security boundary**.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.12](https://img.shields.io/badge/Python-3.12+-green.svg)](https://www.python.org/)
[![GCP](https://img.shields.io/badge/GCP-Vertex%20AI%20%7C%20BigQuery%20%7C%20Model%20Armor-4285F4.svg)](https://cloud.google.com/)

---

## 🚀 1. Run the Demo (Local Preview)

If you just want to see what the dashboard looks like and how blast-radius containment is modeled, you can run it locally with the bundled mock data. No GCP provisioning required.

```bash
uv venv && source .venv/bin/activate       # or: python -m venv .venv
uv pip install -r requirements.txt

python dashboard_backend.py
```
- **Business operations portal** → <http://127.0.0.1:8090/>
- **Governance console** → <http://127.0.0.1:8090/console>

---

## ☁️ 2. Connect Your Own GCP Project

You can use the included Antigravity skill to map your *real* GCP agents, Cloud Run services, and IAM policies, and generate a custom dashboard for your own system.

**Step 1:** Authenticate your local environment to your GCP project.
```bash
export GCP_PROJECT="your-project-id"       # Windows: $env:GCP_PROJECT="your-project-id"
gcloud auth application-default login --project=$GCP_PROJECT
```

**Step 2:** Open this repository in the Antigravity IDE (or your preferred coding agent) and simply ask:
> *"build me a dashboard based on my Gemini agents"*

**Step 3:** The agent will automatically invoke the runbook at `.agents/skills/build-gcp-dashboard/SKILL.md`. It will:
1. Map your Cloud Run services and IAM policies using read-only `gcloud` commands.
2. Ask you clarifying questions about what each agent is *supposed* to do.
3. Flag over-permissioned identities or missing boundaries.
4. Generate a custom `agents_catalog.json` tailored to your environment.

**Step 4:** Restart the backend.
```bash
python dashboard_backend.py
```
The console will now drop the demo mock data and visualize your own live GCP agents and their security blast radiuses!

---

## 🛠️ How It Works (The Reference Architecture)

Beyond generating a dashboard, this repository contains the underlying code (`bootstrap.py`, `containment_matrix.py`, `gcp_auth.py`) that demonstrates *how* to build safe agents. 

You can use these files as a reference architecture for:
- Enforcing least-privilege IAM boundaries so compromised agents cannot access restricted BigQuery datasets or Pub/Sub topics.
- Routing agent prompts through Google Cloud Model Armor.
- Benchmarking model latency and cost (`evals/run_eval.py`).

## 🚦 Evals as a gate, not a report card

`evals/run_eval.py` grades a golden set deterministically — exact field match and
required substrings, no LLM judge — across intent extraction, license gating and RAG
grounding. `evals/baseline.json` is the blessed run, committed, so behavior has a
recorded past to be compared against.

```bash
python evals/run_eval.py                              # measure: all tiers, writes results/latest.json
python evals/run_eval.py --models gemini-2.5-flash-lite --check   # gate: exit 1 on regression
python evals/run_eval.py --promote                    # bless a new baseline (commit the diff)
```

`--check` is a set difference on case IDs, not a delta on an accuracy score. With 26
cases, one flipping pass→fail while another flips fail→pass leaves accuracy identical:
a real regression under a green number. Cost and latency are graded too, because a
prompt change that holds accuracy and doubles spend is also a regression.

`--promote` exists so that accepting a behavior change is a reviewable commit rather
than a deleted check. That is usually the difference between an eval suite that lasts
and one that gets switched off in its second month.

The comparator (`evals/compare.py`) is pure — no network, no clock — so `evals/test_compare.py`
verifies the gate's own logic offline, for free. CI runs those tests on every PR and the
live gate on the cheapest tier only; the full multi-tier sweep stays manual, for choosing
a model rather than defending one.

## License

MIT — see [LICENSE](LICENSE).

# Agent Atlas

**Discover, govern, and visualize your Google Cloud agents with Antigravity (AGY).**

Agent Atlas is a working reference and dashboard generator for multi-agent systems on GCP where **identity, not prompt engineering, is the security boundary**.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.12](https://img.shields.io/badge/Python-3.12+-green.svg)](https://www.python.org/)
[![GCP](https://img.shields.io/badge/GCP-Vertex%20AI%20%7C%20BigQuery%20%7C%20Model%20Armor-4285F4.svg)](https://cloud.google.com/)

---

## 🚀 1. See the example (no Google Cloud account needed)

The repo ships one worked example: **Meridian Clinical Supply**, a fictional pharma
distributor with six agents whose blast radius is enforced by IAM. Without Google Cloud
credentials it runs offline: the pages render, the agent registry and evals are real, and
every live check (Model Armor, the IAM probe) reports `OFFLINE` instead of a verdict. The
header labels it "bundled example" so it cannot be mistaken for your project.

```bash
uv venv && source .venv/bin/activate       # or: python -m venv .venv
uv pip install -r requirements.txt

python dashboard_backend.py
```
- **Business operations portal** → <http://127.0.0.1:8090/>
- **Governance console** → <http://127.0.0.1:8090/console>

With `gcloud auth application-default login` and a project bootstrapped by `bootstrap.py`,
the same example runs live: the 403s on screen come from Google Cloud IAM, not from this app.

---

## 🏢 2. Build it for your business

The example and your dashboard are two separate things. Your business lives in
`agents_catalog.json` (git-ignored, because it names your project and identities). When that
file exists, the dashboard drops Meridian entirely: your name and logo in the header, your
agents in the registry, your protected table and attack prompts in the containment test.
Delete the file and the example comes back.

**Option A — the wizard.** Answers a few questions and writes the catalog. Add `--discover`
to list your Cloud Run services and service accounts first (read-only `gcloud`).

```bash
python atlas_init.py --discover
export GCP_PROJECT="your-project-id"       # Windows: $env:GCP_PROJECT="your-project-id"
python dashboard_backend.py
```

**Option B — a coding agent.** Open the repo in Antigravity (or any agent that reads
`.agents/skills/`) and ask *"build me a dashboard based on my Gemini agents"*. The runbook at
`.agents/skills/build-gcp-dashboard/SKILL.md` maps your services and IAM policies read-only,
asks what each agent is meant to reach, flags over-permissioned identities, and writes the
same catalog.

Either way, check `/api/health`: `"agent_catalog": "generated"` means the console is showing
you, `"bundled-demo"` means it fell back. A catalog with no business name shows
**Your Business Here** until you give it one.

What the catalog does not cover yet, and so stays demo material even with a catalog: the
containment *matrix* grid, the order workflow in the portal, the evals and the RAG corpus.

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

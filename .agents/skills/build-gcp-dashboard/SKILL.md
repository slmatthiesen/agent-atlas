---
name: build-gcp-dashboard
description: >-
  Use this skill when the user asks to build or generate a governance dashboard for their
  own agents, to map their existing Gemini, Cloud Run or other AI agents, or to point this
  repository at a project of their own — including projects that are not (or only partly)
  on Google Cloud. It discovers the agents, writes agents_catalog.json, adds the project as
  a new branded vertical beside the demo, and ends with a no-fabrication verification gate.
---

# Build an agent dashboard for the user's own project

This repository ships a working agent-governance console wired to a demo catalog
(Meridian Clinical / Horizon Realty / Apex Clearing). This runbook re-points it at the
user's project: discover their agents, write a catalog, audit the grants, brand it, and
serve it locally — without showing a single value nobody measured.

A previous run of this skill against a real project is the reason for most rules below.
It hardcoded "3,556 Venues" and "96.9% Fresh" (the database had 4,346 and 124 stale),
invented run ids, Cloud Run URLs ending `-xxxx.run.app`, BigQuery datasets and
"ALLOWED (200 OK)" statuses for a project that runs on EC2, hand-wrote passing eval
scores, labelled a sample trace "Live Sink", made RAG return success when the model call
failed, deleted the demo corpus, left "Meridian" in the header, and deleted the guardrails
from this file. Each rule names the failure it prevents.

## Guardrails

These sections and section 1 stay in this file. **This file is the runbook, not an output
of it** — never edit it during a run. If a rule blocks the user's request, stop and ask.

### Write data, not code

The catalog is `agents_catalog.json`. Never edit `dashboard_backend.py` to insert agents —
an earlier revision did, and shell expansion silently ate a character out of twelve cost
strings (`$0.0780` became `.0780`). The backend loads the JSON file when it exists and falls
back to the bundled demo catalog when it does not. Code changes are for *capabilities*
(a read-only data endpoint, a new vertical's branding), never for *values*.

### Never invent a value

Every count, cost, percentage, run id, timestamp, status, model name and URL the dashboard
shows must be read from a named source — an API response, a SQL query, a log file, `gcloud`
output, the target repo's code — **at render time**, or be rendered as a visible
"no data" state.

- **No metric literals in HTML or JSON.** A panel renders what an endpoint returns. If no
  endpoint returns it, the panel says "no data — <what would produce it>". Why: literal
  numbers look identical to real ones and go stale the moment they are typed.
- **No invented ids.** Run ids, request ids and sink ids come from the run that produced
  them. Why: `run_sf_20260925` pointed at nothing.
- **Eval results only from `evals/run_eval.py`.** Never write `evals/results/*.json` or
  `evals/baseline.json` by hand; never add tasks or models to the results that the harness
  cannot run. Why: the fabricated file had round timestamps, identical token counts and
  case ids that do not exist in `evals/dataset.py`.
- **"Live" means wired.** Label a panel live/measured only when its data comes from a live
  source this backend actually calls. Otherwise keep or add `Sample` / `Demo` labels.
  Why: "● GCP Cloud Logging Live Sink" had no sink behind it.
- **Model names and prices from the target's code or config** (grep for the model id
  string), never recalled. Prices from the provider's pricing page on the day, with the URL
  and date. Why: "Claude 3.5 Haiku" appeared nowhere in the target project.

### Describe what runs, not what GCP could run

The catalog describes the user's real infrastructure. If an agent is a CLI script on EC2,
a pg-boss worker, a cron job or a Lambda, write that as its `type`. Never invent Cloud Run
services, Cloud Functions, BigQuery datasets, GCS buckets, Pub/Sub topics or service
accounts to fit this repo's shape, and never write a placeholder URL (`xxxx`,
`your-project`, `example.com`). A field with no real value is omitted. Why: four
`-xxxx.run.app` endpoints and a `happyhour_analytics` dataset were invented for a project
with none of them.

### Additive, never destructive

Add the user's project as a **new vertical beside the demo ones**. Never delete or rewrite
existing corpus files, demo verticals, demo steps, `evals/baseline.json`, tests, or
sections of this skill. Why: the previous run deleted the Meridian corpus and the
guardrails that would have stopped it.

### Failures surface as failures

No success-shaped fallbacks. If a model, embedding, query or source call fails, the
endpoint returns an error status with the cause, and the UI shows the error. Never return
`GROUNDED_SUCCESS` (or any success status) from an `except` branch, never substitute token
counts, never floor a score (`max(0.45, score)`), never `except Exception: pass`. Why: the
RAG engine returned success with made-up token usage when Vertex was unreachable.

### Brand from the target

Name, tagline, colors, logo and domain vocabulary come from the target project (section 2b),
confirmed by the user. The default view shows the target's brand; demo brands remain only
behind the vertical switcher. Why: a Happy Hour dashboard shipped with "Meridian Clinical"
in the header.

## 1. Ask before you assume

Ask these up front, in one message, and wait for the answers. Every one of them changes
what you write, and none of them is safely guessable.

1. **Which project?** For GCP, the project id — not the display name, not the number. If
   `GCP_PROJECT` is already set, or `gcloud config get-value project` returns one, propose
   it and ask for confirmation rather than adopting it silently. For code, the path to the
   target repository.
2. **Where does it run?** GCP, another cloud, a single VM, local scripts, a mix. Do not
   assume GCP because this repo is about GCP.
3. **Which services are agents?** List what you found and have the user mark them. A Cloud
   Run service is not automatically an agent, and an agent is not automatically a Cloud Run
   service — some run as Cloud Functions, Vertex AI Agent Engine apps, GKE workloads,
   scheduled jobs, queue workers or CLI scripts.
4. **What is each agent meant to reach, in the user's words?** You can read the grants,
   but only the user knows which of them are intentional. That is the difference between a
   finding and a false alarm.
5. **Which numbers should the portal show, and where does each live?** For each one, the
   source (table + query, API, log file) and whether this machine may read it. No source,
   no panel.
6. **Branding:** propose the name, tagline, accent color and logo you found (2b) and ask
   the user to confirm or correct.
7. **Read-only, or may you change the project?** Default to read-only. Ask explicitly
   before running anything that writes: creating a service account, adding a binding,
   enabling an API.

Ask again, mid-run, whenever any of these is true:

- A service has no dedicated service account, so you cannot tell whose identity it runs under.
- Two agents share one identity and you cannot tell whether that is deliberate.
- A grant is broad enough that describing it is a judgement call (`roles/editor`,
  `roles/owner`, a project-level data role).
- A command returns a permission error. Report the exact command and error, and ask how to
  proceed. Do not silently narrow the scan and present the result as complete.
- The user's answer contradicts what the API or code shows. Quote both and let them settle it.
- You are about to write a value and cannot name its source.

State what you are unsure about in the summary rather than resolving it quietly.

## 2. Discover

### 2a. Infrastructure and agents

On GCP, run these read-only and show the user what came back:

```
gcloud config get-value project
gcloud run services list --project=PROJECT --format=json
gcloud iam service-accounts list --project=PROJECT --format=json
gcloud projects get-iam-policy PROJECT --format=json
gcloud asset search-all-resources --scope=projects/PROJECT --format=json
```

Keep the output: every GCP resource in the catalog must appear in it.

Off GCP (or in addition), read the target repo: deploy scripts and infra config
(Dockerfile, compose, Terraform, CI workflows, systemd units, `package.json` scripts),
job/queue handlers, and every call site of a model SDK. Record each agent's entrypoint
file, how it is triggered, what credentials it uses, and what it reads and writes.

Map each agent to the identity it runs as, then to what that identity can reach. That is
the blast radius. What it *cannot* reach is the part worth showing.

### 2b. Brand and vocabulary

Read, in the target repo: README title/tagline, `package.json` / `pyproject.toml` name and
description, site metadata (`<title>`, `metadata` exports, `manifest.json`, OG tags),
CSS theme tokens (`--primary`, Tailwind theme, `globals.css`), favicon / logo SVG, and the
domain nouns the code uses (e.g. venues, windows, stubs — not clinics, SKUs, lots). Present
what you found with file paths; use it only after the user confirms.

### 2c. Data sources for portal panels

For each number the user asked for (question 5), find the query or API that produces it in
the target project and run it read-only once to confirm it works. Write down the exact
query — it goes in the endpoint and in the summary.

## 3. Write agents_catalog.json

One JSON object — `project_id`, `generated_at`, and `agents` keyed by agent id. The console
renders this shape; `title`, `owner`, `runtimeLogin`, `architecture.blastRadius`,
`architecture.blastDesc`, `reachableEndpoints`, `accountsAccess`, `auditLogs` and `gcpLinks`
must be present (arrays may be empty; `gcpLinks` may be `{}`). Values in angle brackets are
slots to fill from discovery — never copy the example text.

```json
{
  "project_id": "<gcp project id, or the target repo name>",
  "generated_at": "<today, YYYY-MM-DD>",
  "agents": {
    "<agent-id>": {
      "id": "<agent-id>",
      "title": "<name the user uses for it>",
      "type": "<what actually runs: Cloud Run Service | CLI script on EC2 | pg-boss worker | cron job | ...>",
      "riskBadge": "<model id read from its code, e.g. the string passed to the SDK>",
      "owner": "<team or person, from the user>",
      "catalogId": "<resource name from gcloud output, or repo path of the entrypoint>",
      "runtimeLogin": "<service account / IAM role / OS user it runs as>",
      "identityType": "<Dedicated Service Account | Shared default compute SA | host credentials | ...>",
      "gcpLinks": {"logs": "<real console or log URL, or omit>", "registry": "<or omit>"},
      "accountsAccess": [
        {"account": "<identity>", "role": "<role or credential scope, as granted>",
         "policy": "<the policy line or config file that grants it>"}
      ],
      "reachableEndpoints": [
        {"name": "<resource>", "type": "<its real type>", "uri": "<its real identifier>",
         "permission": "<the permission, or 'none granted'>",
         "status": "ALLOWED (per IAM policy) | REFUSED (no grant) | UNVERIFIED",
         "statusClass": "endpoint-allowed | endpoint-refused",
         "purpose": "<why it holds this, in the user's words>"}
      ],
      "costNote": "<why cost is unmeasured, e.g. 'no eval covers this workload'>",
      "architecture": {
        "blastRadius": "<one sentence: what it can reach>",
        "blastDesc": "<one sentence: what it cannot>",
        "isolationLevel": "<as identityType>"
      },
      "auditLogs": []
    }
  }
}
```

Rules for what goes in it:

- **`status` is a claim about policy, not a response.** Write ALLOWED/REFUSED only from the
  IAM policy or credential config you read. Never write an HTTP code (`200 OK`,
  `403 accessDenied`) unless you made that request and are quoting it. Unverified →
  `UNVERIFIED` and say why in `purpose`.
- `statusClass` is `endpoint-allowed` / `endpoint-refused` for reachable endpoints; the
  console colours each cell from it, so a mismatch renders a denial as a grant.
- **Cost:** omit `costEstimate` (the console shows "not measured" with `costNote`) unless
  you have a measured cost per request from the target's own usage ledger or an eval run,
  and a request volume from the user. Never compute one from assumed token counts.
- `endpointUrl` is not rendered by the console; include it only if `gcloud` returned it.
- `auditLogs` stays `[]` unless you are reading real log entries (each entry is
  `{"title": ..., "details": [{"label": ..., "val": ...}]}`).
- **Never write this file through a shell string.** Serialize it with a JSON writer. The
  original mangling came from `$0` and `$7` expanding inside a double-quoted heredoc.

Validate it before serving:

```
python -c "import json,pathlib; d=json.loads(pathlib.Path('agents_catalog.json').read_text()); print(len(d['agents']))"
```

`agents_catalog.json` is gitignored on purpose — it names the user's project and identities.

## 4. Add the project as a vertical (portal, corpus, stepper)

Everything here is additive. Know what exists before changing it:

| Surface | Where | Today |
|---|---|---|
| Portal verticals | `business_portal.html`: `BRANDS`, `STEPS_PHARMA/REALTY/FINTECH`, `btnIndustry*`, `switchIndustry("fintech")` at load | Static demo content per vertical |
| Static brand strings | `business_portal.html` `<title>`, `#brandName`, `#mobileBrandTitle`; `agent_console.html` `<title>`, `.brand-text h1`; `dashboard_backend.py` FastAPI `title` and `/api/health` `"project"` | Meridian / generic |
| RAG corpus | `corpus/*.md`, indexed by `rag_engine.py` (Vertex embeddings); console presets in `agent_console.html` | Meridian SOPs |
| Evals | `evals/run_eval.py` `TASKS` + `evals/dataset.py`; calls **Vertex AI Gemini only** | Meridian workloads |
| Containment grid | `containment_matrix.py` `VERTICALS`, probed live against real BigQuery/Pub/Sub | Finance + clinical demo |
| Execution logs | `/api/agent-logs` in `dashboard_backend.py` | Hardcoded Meridian sample, labelled "Sample trace" |
| Portal data panels | — | **No mechanism exists** |

1. **Branding.** Add a `BRANDS` entry and a switcher button for the new vertical, make it
   the load-time default, and update the static brand strings in the table so the first
   paint is already theirs. Keep the demo entries.
2. **Stepper.** Add `STEPS_<VERTICAL>` describing the user's real pipeline stages in their
   vocabulary. Descriptions only — no counts, costs or durations in step text.
3. **Corpus.** Add the user's documents as new `corpus/<vertical>-*.md` files. Only real
   documents they point you to or that exist in their repo; never write "SOPs" yourself.
   Keep the Meridian files. Add RAG presets for the new vertical beside the old ones.
4. **Data panels — build the adapter first.** There is no data-source layer yet. For each
   confirmed source (2c), add a read-only endpoint in `dashboard_backend.py` that runs the
   named query at request time and returns `{"source": "<query or file>", "read_at":
   "<timestamp>", "value": ...}`, or a 503 with the error. Credentials come from env vars,
   never literals; no absolute home-directory paths. The panel fetches that endpoint and
   renders "no data" on error. If the source is not reachable from this machine, ship the
   panel in its "no data" state and say so.
5. **Containment grid.** Add a vertical to `containment_matrix.py` only for GCP resources
   that exist in the 2a output. Otherwise leave the grid on the demo and say so.
6. **Evals.** The harness only runs Vertex Gemini against Meridian tasks. Evaluating the
   user's workloads needs new `TASKS` + dataset cases + (for non-Gemini models) a provider
   in `generate()` — scope that as a separate task and ask before running (it costs real
   tokens). Until then the Evals tab shows the demo's measured results, labelled as demo.
7. **Logs.** Leave `/api/agent-logs` labelled "Sample trace" unless you wire a real log
   source through step 4.

## 5. Audit, and report what you found

Flag each of these with the policy line or config file that evidences it:

- **Over-permissioned identities** — `roles/editor`, `roles/owner`, a project-level data
  role, or a broad API key/DB credential where a scoped one would do.
- **Shared identities** — several services on the default compute service account (or one
  host credential), so neither IAM nor an audit log can tell them apart.
- **Unscoped data access** — a grant on a whole dataset/database where an authorized view
  or read-only role would expose only what the agent needs.
- **Missing perimeter** — no VPC Service Controls (or equivalent) around regulated data.

These are findings for the user to judge. Do not fix them unless asked, and never describe
an unfixed finding as remediated.

## 6. Serve it

```
export GCP_PROJECT=their-project
python dashboard_backend.py
```

- Business operations portal → <http://127.0.0.1:8090/>
- Governance console → <http://127.0.0.1:8090/console>

`/api/health` reports `"agent_catalog": "generated"` when the console is reading their
catalog, and `"bundled-demo"` when it fell back. Check that before telling the user the
dashboard is showing their project. Do not start anything that calls paid APIs without
asking.

## 7. Verification gate — run it, paste the result

Not done until each step has run and its output is in the summary.

1. **Fabrication scan.**
   `python scripts/verify_no_fabrication.py --brand "<Product Name>" --target <path/to/target/repo>`
   It diffs against `main` (plus untracked files and `agents_catalog.json`). **FAIL** lines
   (placeholder URLs, HTTP codes in statuses, literal run ids, home-dir paths, eval tasks or
   case ids the harness cannot produce, demo brand in `<title>`/`<h1>`) must be fixed —
   exit code must be 0. Every **TRACE** line (literal metric in markup, "live" label, broad
   `except`, GCP resource, model name not found in the target) must be either removed or
   listed in the summary with its source.
2. **Panel → source table.** In the summary, one row per displayed number or status:
   panel, endpoint, query/file, value you saw when you ran it. Any panel without a row is
   showing an invented value — remove it.
3. **Eval provenance.** If `evals/results/latest.json` changed, quote the `run_eval.py`
   command you ran and its `generated_at`/`completed_at`. If you did not run it, the file
   must be unchanged (`git diff --stat evals/`).
4. **Leftover demo brand.** `grep -n "Meridian\|Horizon Realty\|Apex Clearing" business_portal.html agent_console.html dashboard_backend.py`
   — every remaining hit must be inside a demo vertical's own entry, not the default view.
5. **Nothing deleted.** `git diff --stat main -- corpus evals/baseline.json .agents test_*.py`
   shows no deletions, and `git diff main -- .agents` is empty.
6. **Tests.** `python -m pytest evals/test_compare.py -q` (offline) and `python -m pytest -q`.
   The full suite needs a GCP project with Application Default Credentials; without one,
   collection fails in `gcp_auth.py`. Report that failure as-is — do not stub it out.

Then say plainly which parts are now theirs (catalog, brand, stepper, any wired panels)
and which are still demo content (containment grid, injection presets, evals, sample logs,
Meridian corpus), and list every question from section 1 you resolved by assumption.

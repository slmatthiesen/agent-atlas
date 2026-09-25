---
name: build-gcp-dashboard
description: >-
  Use this skill when the user asks to build or generate a governance dashboard for their
  own Google Cloud (GCP) agents, to map their existing Gemini or Cloud Run agents, or to
  point this repository at a project of their own.
---

# Build a GCP Agent Dashboard for the user's own project

This repository ships a working agent-governance console wired to a demo catalog. This
runbook re-points it at the user's project: discover their agents, write a catalog, audit
the IAM grants, and serve the dashboard locally.

**Write data, not code.** The catalog is `agents_catalog.json`. Never edit
`dashboard_backend.py` to insert agents — an earlier revision of this runbook did that, and
shell expansion silently ate a character out of twelve cost strings (`$0.0780` became
`.0780`). The backend loads the JSON file when it exists and falls back to the bundled demo
catalog when it does not.

**Never invent numbers.** Every count, cost, percentage, run id, status, and endpoint URL
the dashboard shows must come from something you read — an API response, a query, a log
file — at render time. If you have no source, show "no data" and say so in the summary.
Do not hardcode metrics into the HTML, do not write `evals/results/*.json` by hand (only
`evals/run_eval.py` produces them), and do not label anything "live" unless a live source
is actually wired. An earlier run of this skill filled the portal with plausible city
counts, freshness percentages, and passing eval scores that no run had produced.

Do not delete this section or section 1 while re-pointing the repo at a new project.

## 1. Ask before you assume

Ask these up front, in one message, and wait for the answers. Every one of them changes
what you write, and none of them is safely guessable.

1. **Which project?** The project id — not the display name, not the number. If
   `GCP_PROJECT` is already set, or `gcloud config get-value project` returns one, propose
   it and ask for confirmation rather than adopting it silently.
2. **Which services are agents?** List what you found and have the user mark them. A Cloud
   Run service is not automatically an agent, and an agent is not automatically a Cloud Run
   service — some run as Cloud Functions, Vertex AI Agent Engine apps, GKE workloads, or
   scheduled jobs.
3. **What is each agent meant to reach, in the user's words?** You can read the IAM grants,
   but only the user knows which of them are intentional. That is the difference between a
   finding and a false alarm.
4. **Read-only, or may you change the project?** Default to read-only. Ask explicitly
   before running anything that writes: creating a service account, adding a binding,
   enabling an API.

Ask again, mid-run, whenever any of these is true:

- A service has no dedicated service account, so you cannot tell whose identity it runs under.
- Two agents share one identity and you cannot tell whether that is deliberate.
- A grant is broad enough that describing it is a judgement call (`roles/editor`,
  `roles/owner`, a project-level data role).
- `gcloud` returns a permission error. Report the exact command and error, and ask how to
  proceed. Do not silently narrow the scan and present the result as complete.
- The user's answer contradicts what the API returned. Quote both and let them settle it.

State what you are unsure about in the summary rather than resolving it quietly.

## 2. Discover

Run these read-only. Show the user what came back.

```
gcloud config get-value project
gcloud run services list --project=PROJECT --format=json
gcloud iam service-accounts list --project=PROJECT --format=json
gcloud projects get-iam-policy PROJECT --format=json
gcloud asset search-all-resources --scope=projects/PROJECT --format=json
```

Map each agent to the identity it runs as, then to the grants that identity holds. Those
grants are the blast radius. What an identity is *not* granted is the part worth showing.

## 3. Write agents_catalog.json

One JSON object — `project_id`, `generated_at`, and `agents` keyed by agent id. Match this
shape, which is what the console renders:

```json
{
  "project_id": "their-project",
  "generated_at": "2026-09-11",
  "agents": {
    "svc-quote-bot": {
      "id": "svc-quote-bot",
      "title": "Quote Bot",
      "type": "Cloud Run Service",
      "typeClass": "type-cloudrun",
      "riskBadge": "Gemini 2.5 Flash",
      "riskClass": "risk-dedicated",
      "owner": "team-that-owns-it",
      "catalogId": "projects/their-project/locations/us-central1/services/svc-quote-bot",
      "runtimeLogin": "quote-bot@their-project.iam.gserviceaccount.com",
      "identityType": "Dedicated Service Account",
      "endpointUrl": "https://svc-quote-bot-xxxx.us-central1.run.app",
      "gcpLinks": {"cloudRun": "...", "registry": "...", "logs": "..."},
      "accountsAccess": [
        {"account": "Customer DB", "role": "roles/datastore.viewer", "type": "Firestore DB",
         "status": "Active", "statusClass": "status-active", "policy": "Why it holds this."}
      ],
      "reachableEndpoints": [
        {"name": "Customer DB", "type": "Firestore Database", "uri": "their-project.customers",
         "permission": "datastore.entities.get", "status": "ALLOWED (200 OK)",
         "statusClass": "endpoint-allowed", "purpose": "Reads one customer record."},
        {"name": "Ledger", "type": "BigQuery Table", "uri": "their-project.ledger.entries",
         "permission": "none granted", "status": "REFUSED (403 accessDenied)",
         "statusClass": "endpoint-refused", "purpose": "Holds no grant on the ledger."}
      ],
      "costEstimate": {
        "modelTier": "Gemini 2.5 Flash", "costPer1kOps": "$0.0780", "costPer1kOpsUsd": 0.078,
        "monthlyEstimate": "$7.80 / mo (100k ops)", "efficiency": "vs Pro at equal accuracy",
        "tokenEconomics": "350 in / 100 out", "infraCost": "Cloud Run Scale-to-Zero"
      },
      "architecture": {
        "blastRadius": "One sentence: what it can reach.",
        "blastDesc": "One sentence: what it cannot.",
        "isolationLevel": "Dedicated Service Account",
        "complianceNote": "A control that applies, or omit the field."
      },
      "auditLogs": []
    }
  }
}
```

`statusClass` is `endpoint-allowed` / `endpoint-refused` for reachable endpoints, and
`status-active` / `status-denied` for account access. The console styles each cell from it,
so a mismatch with `status` renders a denial as though it were a grant.

Rules for what goes in it:

- **`status` is a claim.** Write ALLOWED or REFUSED only from what the IAM policy actually
  says. If you did not verify it, say so in `purpose` instead of inventing a response code.
- **Cost figures need a source.** Take the model from the service's own configuration and
  the rate from the Vertex AI pricing page on the day you run it. Without a request volume
  from the user, ask for one or leave `monthlyEstimate` out.
- **Never write this file through a shell string.** Serialize it with a JSON writer. The
  original mangling came from `$0` and `$7` expanding inside a double-quoted heredoc.

Validate it before serving:

```
python -c "import json,pathlib; d=json.loads(pathlib.Path('agents_catalog.json').read_text()); print(len(d['agents']))"
```

## 4. Audit, and report what you found

Flag each of these with the line from the IAM policy that evidences it:

- **Over-permissioned identities** — `roles/editor`, `roles/owner`, or a project-level data
  role where a resource-level grant would do.
- **Shared identities** — several services on the default compute service account, so
  neither IAM nor an audit log can tell them apart.
- **Unscoped data access** — a grant on a whole dataset where an authorized view would
  expose only the columns the agent needs.
- **Missing perimeter** — no VPC Service Controls around a project holding regulated data.

These are findings for the user to judge. Do not fix them unless asked, and never describe
an unfixed finding as remediated.

## 5. Serve it

```
export GCP_PROJECT=their-project
python dashboard_backend.py
```

- Business operations portal → <http://127.0.0.1:8090/>
- Governance console → <http://127.0.0.1:8090/console>

`/api/health` reports `"agent_catalog": "generated"` when the console is reading their
catalog, and `"bundled-demo"` when it fell back. Check that before telling the user the
dashboard is showing their project.

Then say plainly which parts are now theirs and which are still demo content. The agent
registry and the blast-radius descriptions come from their catalog. The containment matrix,
the injection presets, the evals, and the RAG corpus remain this repository's demo material
until they are run against the user's own project.

# For coding agents opening this repository

Agent Atlas ships one worked example, **Meridian Clinical Supply**, a fictional pharma
distributor. It is not the user's project. The user's project lives in `agents_catalog.json`,
which is git-ignored and does not exist until it is generated.

Before you start the dashboard:

1. **If the user has a Google Cloud project, offer to build it for them first.** Run
   `python atlas_init.py --discover` (interactive, read-only `gcloud`), or follow
   `.agents/skills/build-gcp-dashboard/SKILL.md` to map their services and IAM yourself.
   Ask which project, which services are agents, and which table no agent may read.
2. **If they only want to look, start the example and say so.** `python dashboard_backend.py`
   with no catalog serves Meridian, labelled "bundled example" in the header. Without
   credentials it runs offline and every live check reports `OFFLINE`, not a verdict.
3. **Never describe the example's agents, tables or 403s as the user's.** Check
   `/api/health`: `"agent_catalog": "generated"` means it is theirs, `"bundled-demo"` means
   it is not. Even with a catalog, the containment matrix grid, the portal's order workflow,
   the evals and the RAG corpus remain example material.

Write data, not code: the catalog is JSON. Do not edit `dashboard_backend.py` to add agents.

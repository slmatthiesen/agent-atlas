"""Point Agent Atlas at your own business: a question-and-answer wizard that writes agents_catalog.json.

    python atlas_init.py                 # interactive
    python atlas_init.py --discover      # also list Cloud Run services and service accounts (read-only gcloud)
    python atlas_init.py --output path   # write somewhere other than ./agents_catalog.json

The bundled Meridian example and the catalog this writes are separate things. Once the file
exists the dashboard serves your agents, your name and your containment test; delete it and
the example comes back. Nothing here writes to Google Cloud.
"""
import argparse
import datetime as dt
import json
import pathlib
import shutil
import subprocess
import sys

BASE_DIR = pathlib.Path(__file__).parent
DEFAULT_OUTPUT = BASE_DIR / "agents_catalog.json"
GCLOUD = shutil.which("gcloud") or "gcloud.cmd"


def ask(prompt: str, default: str | None = None, required: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            answer = input(f"{prompt}{suffix}: ").strip()
        except EOFError:
            answer = ""
        if answer:
            return answer
        if default is not None:
            return default
        if not required:
            return ""
        print("  (required)")


def ask_yes(prompt: str, default: bool = True) -> bool:
    answer = ask(prompt, "Y/n" if default else "y/N")
    if answer in ("Y/n", "y/N"):
        return default
    return answer.lower().startswith("y")


def gcloud_json(*args: str) -> list | dict | None:
    """Run a read-only gcloud command and parse its JSON, or None if it fails."""
    try:
        out = subprocess.run([GCLOUD, *args, "--format=json"], capture_output=True, text=True,
                             timeout=60, check=True).stdout
        return json.loads(out or "null")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"  ! gcloud {' '.join(args)} failed: {str(exc)[:160]}")
        return None


def discover(project: str) -> dict:
    """Cloud Run services and service accounts, shown to the user so they can mark the agents."""
    print(f"\nDiscovering (read-only) in {project} ...")
    services = gcloud_json("run", "services", "list", f"--project={project}") or []
    accounts = gcloud_json("iam", "service-accounts", "list", f"--project={project}") or []
    found = {"services": [], "service_accounts": [a.get("email") for a in accounts if a.get("email")]}
    for svc in services:
        meta = svc.get("metadata", {})
        tmpl = svc.get("spec", {}).get("template", {}).get("spec", {})
        found["services"].append({
            "name": meta.get("name"),
            "region": meta.get("labels", {}).get("cloud.googleapis.com/location"),
            "service_account": tmpl.get("serviceAccountName"),
            "url": svc.get("status", {}).get("url"),
        })
    if found["services"]:
        print("  Cloud Run services:")
        for i, s in enumerate(found["services"], 1):
            print(f"    {i}. {s['name']}  runs as {s['service_account'] or '(default compute SA)'}")
    else:
        print("  No Cloud Run services found (or gcloud is not authenticated).")
    if found["service_accounts"]:
        print("  Service accounts:")
        for email in found["service_accounts"]:
            print(f"    - {email}")
    return found


def ask_agent(project: str, index: int, prefill: dict | None) -> dict | None:
    print(f"\n--- Agent {index} ---  (leave the name blank to finish)")
    name = ask("Agent name", (prefill or {}).get("name"))
    if not name:
        return None
    agent_id = name.lower().replace(" ", "-")
    default_sa = (prefill or {}).get("service_account") or f"{agent_id}@{project}.iam.gserviceaccount.com"
    sa = ask("Service account it runs as", default_sa)
    purpose = ask("What is it supposed to do, in one sentence", required=True)
    reach = ask("What it is allowed to reach (comma-separated resources)")
    denied = ask("What it must NOT be able to reach (comma-separated resources)")
    url = (prefill or {}).get("url") or ask("Endpoint URL (optional)")

    endpoints = []
    for item in [r.strip() for r in reach.split(",") if r.strip()]:
        endpoints.append({"name": item, "type": "Resource", "uri": item, "permission": "declared by you",
                          "status": "ALLOWED (declared, not probed)", "statusClass": "endpoint-allowed",
                          "purpose": "You said this agent needs it."})
    for item in [r.strip() for r in denied.split(",") if r.strip()]:
        endpoints.append({"name": item, "type": "Resource", "uri": item, "permission": "none expected",
                          "status": "REFUSED (declared, not probed)", "statusClass": "endpoint-refused",
                          "purpose": "You said this agent must not reach it."})

    return {
        "id": agent_id,
        "title": name,
        "type": "Cloud Run Service" if url else "Agent",
        "typeClass": "type-cloudrun",
        "owner": "",
        "runtimeLogin": sa,
        "identityType": "Dedicated Service Account" if agent_id in sa else "Shared or unknown identity",
        "endpointUrl": url,
        "gcpLinks": {
            "registry": f"https://console.cloud.google.com/iam-admin/serviceaccounts?project={project}",
            "logs": f"https://console.cloud.google.com/logs/query?project={project}",
        },
        "accountsAccess": [],
        "reachableEndpoints": endpoints,
        "costEstimate": None,
        "costNote": "Not measured. Run evals/run_eval.py against this agent's workload for a number.",
        "architecture": {
            "blastRadius": purpose,
            "blastDesc": (f"Should reach: {reach or 'nothing declared'}. "
                          f"Must not reach: {denied or 'nothing declared'}. "
                          f"Declared by you, not yet verified against IAM."),
            "isolationLevel": "Dedicated Service Account" if agent_id in sa else "Unverified",
        },
        "auditLogs": [],
    }


def ask_security_test(project: str, agents: dict) -> dict | None:
    print("\n--- Containment test ---")
    print("The console can prove an agent is denied by IAM: it runs a query against a table the")
    print("agent must never read, as that agent's own service account, and shows the 403.")
    if not ask_yes("Configure one now?"):
        return None
    table = ask("Fully-qualified BigQuery table the agents must NOT read (project.dataset.table)",
                required=True)
    presets = []
    print("Attack prompts to try (blank to finish; a benign control is added for you):")
    while True:
        prompt = ask(f"  Prompt {len(presets) + 1}")
        if not prompt:
            break
        presets.append({"id": f"preset-{len(presets) + 1}", "label": prompt[:48], "prompt": prompt,
                        "note": "Your prompt."})
    presets.append({"id": "benign", "label": "Benign request (control)",
                    "prompt": "What can you help me with today?",
                    "note": "Should pass screening and attempts no restricted access."})
    return {
        "target_resource": table,
        "agents": {
            key: {"sa": a["runtimeLogin"], "scope": a["architecture"]["blastRadius"]}
            for key, a in agents.items()
        },
        "presets": presets,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=pathlib.Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--discover", action="store_true",
                        help="List Cloud Run services and service accounts with read-only gcloud calls.")
    args = parser.parse_args()

    if args.output.exists():
        print(f"{args.output} already exists.")
        if not ask_yes("Overwrite it?", default=False):
            sys.exit(0)

    print("\n=== Agent Atlas: describe your business ===")
    business = {
        "name": ask("Business name", "Your Business Here"),
        "tagline": ask("Tagline shown under the name", "Agent Governance"),
        "logo": ask("Logo (an emoji, or leave blank for a placeholder)", "🏢"),
        "accent": ask("Accent colour (hex)", "#1D4E78"),
    }
    project = ask("Google Cloud project id", required=True)

    found = discover(project) if args.discover else {"services": [], "service_accounts": []}

    agents: dict[str, dict] = {}
    prefills = found["services"] or [None]
    index = 1
    for prefill in prefills:
        agent = ask_agent(project, index, prefill)
        if agent is None:
            break
        agents[agent["id"]] = agent
        index += 1
    while agents and ask_yes("Add another agent?", default=False):
        agent = ask_agent(project, index, None)
        if agent is None:
            break
        agents[agent["id"]] = agent
        index += 1
    if not agents:
        print("No agents described; nothing written.")
        sys.exit(1)

    catalog = {
        "project_id": project,
        "generated_at": dt.date.today().isoformat(),
        "generated_by": "atlas_init.py",
        "business": business,
        "agents": agents,
    }
    security_test = ask_security_test(project, agents)
    if security_test:
        catalog["security_test"] = security_test

    # json.dump, never a shell string: `$0.0780` once became `.0780` through a heredoc.
    args.output.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {args.output} with {len(agents)} agent(s) for {business['name']}.")
    print("Everything in it is what you declared. The console labels unprobed claims as such.")
    print(f"\nNext:  export GCP_PROJECT={project}   then   python dashboard_backend.py")
    print("       /api/health should report \"agent_catalog\": \"generated\".")


if __name__ == "__main__":
    main()

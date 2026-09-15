"""Provision this demo into your own Google Cloud project.

Replaces the Windows-only `apply_iam_grants.ps1` with something that runs anywhere and
is safe to re-run — every step is idempotent, so a partial failure can be fixed and the
script run again.

    export GCP_PROJECT=your-project-id
    gcloud auth application-default login --project=$GCP_PROJECT
    python bootstrap.py

Requires the gcloud CLI on PATH and Owner (or equivalent) on the target project.
"""
import argparse
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

from gcp_auth import PROJECT_ID, REGION, get_access_token

sys.stdout.reconfigure(encoding="utf-8")

REQUIRED_APIS = [
    "aiplatform.googleapis.com",
    "modelarmor.googleapis.com",
    "bigquery.googleapis.com",
    "firestore.googleapis.com",
    "pubsub.googleapis.com",
    "run.googleapis.com",
    # Every agent call goes through service-account impersonation, so this one is
    # load-bearing — without it the containment tests fail at credential refresh.
    "iamcredentials.googleapis.com",
]

# The narrow grants each agent identity holds. These ARE the demo: the containment
# behaviour is a direct consequence of what is absent here. Note that no agent is granted
# any read role on the clinical_records dataset — agent-ship reaches the address view only
# through BigQuery's authorized-view mechanism, applied by authorize_bq_view.py.
AGENTS = {
    "agent-intake": {
        "display": "Voice frontdoor — spoken order intake",
        "project_roles": ["roles/aiplatform.user"],
    },
    "agent-sales": {
        "display": "Sales agent — quoting and cart building",
        "project_roles": ["roles/aiplatform.user", "roles/datastore.user"],
    },
    "agent-verify": {
        "display": "Verification agent — licence gate",
        "project_roles": ["roles/aiplatform.user", "roles/datastore.user"],
        "topic_publisher": ["order.verified"],
    },
    "agent-fulfill": {
        "display": "Fulfillment agent — FEFO allocation",
        "project_roles": ["roles/aiplatform.user", "roles/datastore.user"],
        "topic_publisher": ["order.packed"],
        "subscription_subscriber": ["order.verified-sub"],
    },
    "agent-ship": {
        "display": "Shipping agent — cold-chain logistics",
        # jobUser lets it *run* a query; it still needs data access per-resource, which is
        # why the raw patient table stays unreadable to it.
        "project_roles": ["roles/aiplatform.user", "roles/datastore.user", "roles/bigquery.jobUser"],
        "subscription_subscriber": ["order.packed-sub"],
    },
    "agent-reconcile": {
        "display": "Reconcile agent — analytics and expiry audit",
        "project_roles": ["roles/aiplatform.user", "roles/datastore.viewer", "roles/bigquery.jobUser"],
        "topic_publisher": ["reconcile.recommendations"],
    },
    # Finance vertical. Same rule as above: what each one CANNOT do is the demo.
    # None of these hold any role on the `ledger` dataset — they reach it only through
    # the authorized views applied by finance_seed.py.
    "agent-txn-monitor": {
        "display": "Transaction monitoring — reads the feed, moves nothing",
        # jobUser runs a query; the per-view grant decides what it can see. No publisher
        # role anywhere, so a compromised monitor cannot initiate a payment.
        "project_roles": ["roles/aiplatform.user", "roles/bigquery.jobUser"],
    },
    "agent-payments": {
        "display": "Payment agent — the only identity that can request a send",
        "project_roles": ["roles/aiplatform.user", "roles/bigquery.jobUser"],
        "topic_publisher": ["payment.requested"],
    },
    "agent-nightly-recon": {
        "display": "Nightly reconciliation — reads everything, cannot move money",
        "project_roles": ["roles/aiplatform.user", "roles/bigquery.jobUser"],
        "topic_publisher": ["recon.findings"],
        "subscription_subscriber": ["payment.requested-sub"],
    },
    "dashboard-backend": {
        "display": "Dashboard backend — read-only estate inspection",
        "project_roles": ["roles/run.viewer", "roles/cloudasset.viewer", "roles/bigquery.jobUser"],
    },
}

TOPICS = ["order.verified", "order.packed", "reconcile.recommendations",
          "payment.requested", "recon.findings"]
SUBSCRIPTIONS = {"order.verified-sub": "order.verified", "order.packed-sub": "order.packed",
                 "payment.requested-sub": "payment.requested"}

MODEL_ARMOR_TEMPLATE = "meridian-agent-armor"

# gcloud is a .cmd shim on Windows; CreateProcess needs the resolved path.
GCLOUD = shutil.which("gcloud") or "gcloud.cmd"

_failures: list[str] = []


def run(args: list[str], *, tolerate: bool = False) -> bool:
    """Run a gcloud command, reporting rather than raising. Returns True on success."""
    result = subprocess.run([GCLOUD, *args[1:]], capture_output=True, text=True)
    if result.returncode == 0:
        return True
    stderr = (result.stderr or "").strip()
    # Re-running a completed bootstrap should be quiet, not noisy.
    if tolerate and any(s in stderr for s in ("already exists", "ALREADY_EXISTS")):
        return True
    print(f"    ! {' '.join(args[:4])}… failed: {stderr.splitlines()[-1] if stderr else 'unknown'}")
    _failures.append(" ".join(args))
    return False


def sa_email(name: str) -> str:
    return f"{name}@{PROJECT_ID}.iam.gserviceaccount.com"


def enable_apis() -> None:
    print("\n[1/6] Enabling required APIs (this can take a minute)…")
    run(["gcloud", "services", "enable", *REQUIRED_APIS, f"--project={PROJECT_ID}"])
    print("    done")


def create_service_accounts() -> None:
    print("\n[2/6] Creating service accounts…")
    for name, spec in AGENTS.items():
        ok = run(["gcloud", "iam", "service-accounts", "create", name,
                  f"--project={PROJECT_ID}", f"--display-name={spec['display']}"], tolerate=True)
        print(f"    {'✓' if ok else '✗'} {sa_email(name)}")


def create_pubsub() -> None:
    print("\n[3/6] Creating Pub/Sub topics and subscriptions…")
    for topic in TOPICS:
        run(["gcloud", "pubsub", "topics", "create", topic, f"--project={PROJECT_ID}"], tolerate=True)
        print(f"    ✓ topic {topic}")
    for subscription, topic in SUBSCRIPTIONS.items():
        run(["gcloud", "pubsub", "subscriptions", "create", subscription,
             f"--topic={topic}", f"--project={PROJECT_ID}"], tolerate=True)
        print(f"    ✓ subscription {subscription}")


def apply_iam() -> None:
    print("\n[4/6] Applying least-privilege IAM grants…")
    for name, spec in AGENTS.items():
        member = f"serviceAccount:{sa_email(name)}"
        for role in spec.get("project_roles", []):
            run(["gcloud", "projects", "add-iam-policy-binding", PROJECT_ID,
                 f"--member={member}", f"--role={role}", "--quiet",
                 "--condition=None"])
        for topic in spec.get("topic_publisher", []):
            run(["gcloud", "pubsub", "topics", "add-iam-policy-binding", topic,
                 f"--member={member}", "--role=roles/pubsub.publisher",
                 f"--project={PROJECT_ID}", "--quiet"])
        for subscription in spec.get("subscription_subscriber", []):
            run(["gcloud", "pubsub", "subscriptions", "add-iam-policy-binding", subscription,
                 f"--member={member}", "--role=roles/pubsub.subscriber",
                 f"--project={PROJECT_ID}", "--quiet"])
        roles = len(spec.get("project_roles", []))
        print(f"    ✓ {name} ({roles} project role{'s' if roles != 1 else ''})")


def create_model_armor_template() -> None:
    """Create the prompt-injection template Layer 2 screens against.

    Model Armor lives on the regional endpoint; the global host answers 403.
    """
    print("\n[5/6] Creating the Model Armor template…")
    url = (f"https://modelarmor.{REGION}.rep.googleapis.com/v1"
           f"/projects/{PROJECT_ID}/locations/{REGION}/templates"
           f"?template_id={MODEL_ARMOR_TEMPLATE}")
    body = {
        "filterConfig": {
            "piAndJailbreakFilterSettings": {
                "filterEnforcement": "ENABLED",
                "confidenceLevel": "LOW_AND_ABOVE",
            },
            "maliciousUriFilterSettings": {"filterEnforcement": "ENABLED"},
        }
    }
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {get_access_token()}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60):
            print(f"    ✓ created template '{MODEL_ARMOR_TEMPLATE}'")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:200]
        if exc.code == 409 or "already exists" in detail.lower():
            print(f"    ✓ template '{MODEL_ARMOR_TEMPLATE}' already exists")
        else:
            print(f"    ! could not create template: {exc.code} {detail}")
            _failures.append("model armor template")
            return

    print(f"\n    Set this so the gateway screens against it:")
    print(f"      export MODEL_ARMOR_TEMPLATE={MODEL_ARMOR_TEMPLATE}")


def seed_data() -> None:
    print("\n[6/6] Seeding Firestore and BigQuery…")
    for script in ["setup_and_seed.py", "authorize_bq_view.py", "setup_audit_sink.py"]:
        print(f"    → {script}")
        result = subprocess.run([sys.executable, script], capture_output=True, text=True)
        if result.returncode != 0:
            tail = (result.stderr or result.stdout or "").strip().splitlines()[-3:]
            print("      ! failed:")
            for line in tail:
                print(f"        {line}")
            _failures.append(script)
        else:
            print("      ✓ ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-seed", action="store_true", help="Only provision identities and IAM.")
    args = parser.parse_args()

    if not shutil.which("gcloud"):
        sys.exit("gcloud CLI not found on PATH. Install it: https://cloud.google.com/sdk/docs/install")

    print("=" * 68)
    print(f"Provisioning the agent governance demo")
    print(f"  project: {PROJECT_ID}")
    print(f"  region:  {REGION}")
    print("=" * 68)

    enable_apis()
    create_service_accounts()
    create_pubsub()
    apply_iam()
    create_model_armor_template()
    if not args.skip_seed:
        seed_data()

    print("\n" + "=" * 68)
    if _failures:
        print(f"Finished with {len(_failures)} problem(s). This script is safe to re-run.")
        for failure in _failures:
            print(f"  - {failure[:100]}")
        sys.exit(1)

    print("Done. Next:")
    print("  python evals/run_eval.py     # measure accuracy and cost on your project")
    print("  python dashboard_backend.py  # then open http://127.0.0.1:8090")
    print("=" * 68)


if __name__ == "__main__":
    main()

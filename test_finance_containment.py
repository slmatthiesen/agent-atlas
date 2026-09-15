"""Containment proof for the finance vertical. Exits non-zero if any boundary is open.

Every assertion here is a real call to Google Cloud under the agent's own service account.
Nothing is mocked and nothing is checked in application code — a PASS means Google Cloud
itself refused, and a FAIL means an agent can reach money it should not.

    export GCP_PROJECT=your-project-id
    python test_finance_containment.py

Run after bootstrap.py and finance_seed.py.
"""
import sys

from google.api_core.exceptions import Forbidden, NotFound, PermissionDenied
from google.cloud import bigquery, pubsub_v1

from gcp_auth import PROJECT_ID, agent_sa, get_impersonated_credentials

sys.stdout.reconfigure(encoding="utf-8")

LEDGER_ACCOUNTS = f"`{PROJECT_ID}.ledger.bank_accounts`"
LEDGER_TRANSACTIONS = f"`{PROJECT_ID}.ledger.transactions`"
FACTS_VIEW = f"`{PROJECT_ID}.finance_analytics.transaction_facts`"
FUNDING_VIEW = f"`{PROJECT_ID}.finance_analytics.account_funding_status`"

failures: list[str] = []


def bq(agent: str) -> bigquery.Client:
    return bigquery.Client(project=PROJECT_ID, credentials=get_impersonated_credentials(agent_sa(agent)))


def expect_allowed(label: str, agent: str, sql: str) -> None:
    try:
        rows = list(bq(agent).query(sql).result())
        print(f"  ✅ {label} — {len(rows)} row(s)")
    except (Forbidden, PermissionDenied) as exc:
        print(f"  ❌ {label} — DENIED, but this access is supposed to work: {exc.message}")
        failures.append(label)


def expect_denied(label: str, agent: str, sql: str) -> None:
    try:
        list(bq(agent).query(sql).result())
        print(f"  ❌ {label} — ALLOWED. Containment is broken.")
        failures.append(label)
    except (Forbidden, PermissionDenied):
        print(f"  ✅ {label} — 403 from Google Cloud IAM")
    except NotFound:
        print(f"  ❌ {label} — resource missing; run finance_seed.py first")
        failures.append(label)


def expect_publish_denied(label: str, agent: str, topic: str) -> None:
    publisher = pubsub_v1.PublisherClient(credentials=get_impersonated_credentials(agent_sa(agent)))
    try:
        publisher.publish(publisher.topic_path(PROJECT_ID, topic), b'{"probe":true}').result()
        print(f"  ❌ {label} — PUBLISHED. This identity can move money.")
        failures.append(label)
    except (Forbidden, PermissionDenied):
        print(f"  ✅ {label} — 403 from Pub/Sub IAM")


def expect_publish_allowed(label: str, agent: str, topic: str) -> None:
    publisher = pubsub_v1.PublisherClient(credentials=get_impersonated_credentials(agent_sa(agent)))
    try:
        publisher.publish(publisher.topic_path(PROJECT_ID, topic), b'{"probe":true}').result()
        print(f"  ✅ {label}")
    except (Forbidden, PermissionDenied) as exc:
        print(f"  ❌ {label} — DENIED, but this publish is supposed to work: {exc}")
        failures.append(label)


print(f"=== Finance containment · {PROJECT_ID} ===")

print("\n[1] Transaction monitor sees the feed, never the account")
expect_allowed("monitor reads transaction_facts", "txn-monitor", f"SELECT txn_id FROM {FACTS_VIEW} LIMIT 5")
expect_denied("monitor reads the raw transactions table", "txn-monitor", f"SELECT * FROM {LEDGER_TRANSACTIONS} LIMIT 1")
expect_denied("monitor reads account numbers and balances", "txn-monitor", f"SELECT * FROM {LEDGER_ACCOUNTS} LIMIT 1")

print("\n[2] Payment agent learns sufficiency, never the balance")
expect_allowed("payments reads account_funding_status", "payments", f"SELECT account_id, is_funded FROM {FUNDING_VIEW} LIMIT 5")
expect_denied("payments reads the balance behind that view", "payments", f"SELECT balance_cents FROM {LEDGER_ACCOUNTS} LIMIT 1")
expect_denied("payments reads the transaction history", "payments", f"SELECT txn_id FROM {FACTS_VIEW} LIMIT 1")

print("\n[3] Nightly job reads everything and moves nothing")
expect_allowed("nightly-recon reads transaction_facts", "nightly-recon", f"SELECT txn_id FROM {FACTS_VIEW} LIMIT 5")
expect_denied("nightly-recon reads account numbers", "nightly-recon", f"SELECT account_number FROM {LEDGER_ACCOUNTS} LIMIT 1")
expect_publish_allowed("nightly-recon publishes recon.findings", "nightly-recon", "recon.findings")
expect_publish_denied("nightly-recon requests a payment", "nightly-recon", "payment.requested")

print("\n[4] Only the payment agent can request a send")
expect_publish_denied("monitor requests a payment", "txn-monitor", "payment.requested")
expect_publish_allowed("payments requests a payment", "payments", "payment.requested")

if failures:
    print(f"\n❌ {len(failures)} boundary/boundaries not holding:")
    for failure in failures:
        print(f"    · {failure}")
    sys.exit(1)

print("\n✅ Every boundary held. The denials came from Google Cloud, not from this code.")

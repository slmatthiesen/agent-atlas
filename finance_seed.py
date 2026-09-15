"""Provision the small-business finance vertical: protected ledger, two authorized views.

The clinical vertical proves containment over medical records. This one proves it over
money, which is the version most people have an intuition for: a monitoring agent that
can see every transaction but no account number, a payments agent that can learn whether
funds are sufficient without ever reading a balance, and a nightly job that can read
everything and move nothing.

Safe to re-run — datasets and tables are created if absent, and seed data is loaded with
WRITE_TRUNCATE so a second run reproduces the first.

    export GCP_PROJECT=your-project-id
    python finance_seed.py

Run after bootstrap.py, which creates the service accounts this grants to.
"""
import sys

from google.api_core.exceptions import Conflict, NotFound
from google.cloud import bigquery

from gcp_auth import PROJECT_ID, agent_sa, get_base_credentials

sys.stdout.reconfigure(encoding="utf-8")

LEDGER = "ledger"
ANALYTICS = "finance_analytics"

MONITOR_SA = agent_sa("txn-monitor")
PAYMENTS_SA = agent_sa("payments")
RECON_SA = agent_sa("nightly-recon")

ACCOUNT_SCHEMA = [
    bigquery.SchemaField("account_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("business_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("business_name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("account_number", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("routing_number", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("balance_cents", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("daily_send_limit_cents", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("is_synthetic", "STRING", mode="REQUIRED"),
]

TRANSACTION_SCHEMA = [
    bigquery.SchemaField("txn_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("account_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("business_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("posted_at", "TIMESTAMP", mode="REQUIRED"),
    # Money is integer minor units everywhere in this vertical. A float column here
    # would quietly reintroduce the rounding it exists to avoid.
    bigquery.SchemaField("amount_cents", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("direction", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("counterparty", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("category", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("status", "STRING", mode="REQUIRED"),
]

SYNTHETIC = "SYNTHETIC_DATA_DO_NOT_USE_REAL_FINANCIAL_RECORDS"

ACCOUNTS = [
    {
        "account_id": "ACCT-1001", "business_id": "BIZ-4471",
        "business_name": "SYNTHETIC Northwind Coffee Roasters",
        "account_number": "000123456789", "routing_number": "021000021",
        "balance_cents": 4_812_600, "daily_send_limit_cents": 2_500_000,
        "is_synthetic": SYNTHETIC,
    },
    {
        "account_id": "ACCT-1002", "business_id": "BIZ-4471",
        "business_name": "SYNTHETIC Northwind Coffee Roasters",
        "account_number": "000123456790", "routing_number": "021000021",
        "balance_cents": 91_400, "daily_send_limit_cents": 500_000,
        "is_synthetic": SYNTHETIC,
    },
    {
        "account_id": "ACCT-2001", "business_id": "BIZ-9021",
        "business_name": "SYNTHETIC Lumen Design Studio",
        "account_number": "000998877665", "routing_number": "121000248",
        "balance_cents": 268_900, "daily_send_limit_cents": 1_000_000,
        "is_synthetic": SYNTHETIC,
    },
]

TRANSACTIONS = [
    ("TXN-70001", "ACCT-1001", "BIZ-4471", "2026-08-01T14:02:00Z", -184_250, "debit", "Gusto", "payroll", "posted"),
    ("TXN-70002", "ACCT-1001", "BIZ-4471", "2026-08-01T16:41:00Z", 920_000, "credit", "Stripe Payouts", "revenue", "posted"),
    ("TXN-70003", "ACCT-1001", "BIZ-4471", "2026-08-03T09:15:00Z", -42_900, "debit", "AWS", "cloud", "posted"),
    ("TXN-70004", "ACCT-1002", "BIZ-4471", "2026-08-04T11:30:00Z", -9_900, "debit", None, "uncategorized", "posted"),
    ("TXN-70005", "ACCT-1001", "BIZ-4471", "2026-08-05T02:11:00Z", -1_480_000, "debit", "Meridian Holdings LLC", "transfer", "posted"),
    ("TXN-70006", "ACCT-1001", "BIZ-4471", "2026-08-05T02:14:00Z", -1_490_000, "debit", "Meridian Holdings LLC", "transfer", "posted"),
    ("TXN-70007", "ACCT-1001", "BIZ-4471", "2026-08-05T02:17:00Z", -1_470_000, "debit", "Meridian Holdings LLC", "transfer", "pending"),
    ("TXN-70008", "ACCT-2001", "BIZ-9021", "2026-08-06T13:05:00Z", -31_200, "debit", "Figma", "software", "posted"),
    ("TXN-70009", "ACCT-2001", "BIZ-9021", "2026-08-07T08:45:00Z", 145_000, "credit", "Client Wire — Acme", "revenue", "posted"),
    ("TXN-70010", "ACCT-2001", "BIZ-9021", "2026-08-07T08:45:00Z", 145_000, "credit", "Client Wire — Acme", "revenue", "posted"),
]

# The view a monitoring agent gets. Everything it needs to spot a pattern; nothing it
# could use to move money or identify the account externally.
TRANSACTION_FACTS_SQL = f"""
SELECT txn_id, business_id, posted_at, amount_cents, direction, counterparty, category, status
FROM `{PROJECT_ID}.{LEDGER}.transactions`
"""

# The view a payments agent gets. It answers "can this send clear?" without ever
# disclosing the balance, the account number, or the routing number.
ACCOUNT_FUNDING_SQL = f"""
SELECT
  account_id,
  business_id,
  business_name,
  balance_cents > 0 AS is_funded,
  CASE
    WHEN balance_cents >= 1000000 THEN 'ABOVE_10K'
    WHEN balance_cents >= 100000 THEN 'ABOVE_1K'
    ELSE 'BELOW_1K'
  END AS balance_band,
  daily_send_limit_cents
FROM `{PROJECT_ID}.{LEDGER}.bank_accounts`
"""


def ensure_dataset(client, dataset_id, description):
    dataset = bigquery.Dataset(f"{PROJECT_ID}.{dataset_id}")
    dataset.location = "US"
    dataset.description = description
    try:
        client.create_dataset(dataset)
        print(f"    created dataset {dataset_id}")
    except Conflict:
        print(f"    dataset {dataset_id} already exists")


def load_table(client, table_id, schema, rows):
    """Create-if-absent, then replace the contents. A load job is used rather than
    streaming inserts so the rows are queryable immediately and a re-run is a no-op."""
    full_id = f"{PROJECT_ID}.{table_id}"
    try:
        client.get_table(full_id)
    except NotFound:
        client.create_table(bigquery.Table(full_id, schema=schema))
        print(f"    created table {table_id}")
    job = client.load_table_from_json(
        rows, full_id,
        job_config=bigquery.LoadJobConfig(schema=schema, write_disposition="WRITE_TRUNCATE"),
    )
    job.result()
    print(f"    loaded {len(rows)} rows into {table_id}")


def ensure_view(client, view_id, sql):
    full_id = f"{PROJECT_ID}.{view_id}"
    view = bigquery.Table(full_id)
    view.view_query = sql
    try:
        client.create_table(view)
        print(f"    created view {view_id}")
    except Conflict:
        client.update_table(view, ["view_query"])
        print(f"    updated view {view_id}")


def authorize_views(client, view_ids):
    """Let the views read the protected dataset without granting their readers access to it.

    This is the mechanism the whole demo turns on: the agent has no role on `ledger` at
    all, so the only path to that data is through a view whose columns someone chose.
    """
    dataset = client.get_dataset(f"{PROJECT_ID}.{LEDGER}")
    entries = list(dataset.access_entries)
    existing = {
        e.entity_id.get("tableId")
        for e in entries
        if e.entity_type == "view" and isinstance(e.entity_id, dict)
    }
    added = []
    for view_id in view_ids:
        table_id = view_id.split(".")[-1]
        if table_id in existing:
            continue
        entries.append(bigquery.AccessEntry(
            role=None, entity_type="view",
            entity_id={"projectId": PROJECT_ID, "datasetId": ANALYTICS, "tableId": table_id},
        ))
        added.append(table_id)
    if added:
        dataset.access_entries = entries
        client.update_dataset(dataset, ["access_entries"])
    print(f"    authorized on {LEDGER}: {', '.join(added) if added else 'already authorized'}")


def grant_view_reader(client, view_id, sa_email):
    """Table-level dataViewer on one view. Not the dataset — the view."""
    table = client.get_table(f"{PROJECT_ID}.{view_id}")
    policy = client.get_iam_policy(table)
    member = f"serviceAccount:{sa_email}"
    for binding in policy.bindings:
        if binding.get("role") == "roles/bigquery.dataViewer" and member in binding.get("members", []):
            print(f"    {sa_email.split('@')[0]} already reads {view_id}")
            return
    policy.bindings.append({"role": "roles/bigquery.dataViewer", "members": [member]})
    client.set_iam_policy(table, policy)
    print(f"    granted {sa_email.split('@')[0]} reader on {view_id}")


def main():
    client = bigquery.Client(project=PROJECT_ID, credentials=get_base_credentials())
    print(f"=== Finance vertical → {PROJECT_ID} ===")

    print("\n[1/5] Datasets")
    ensure_dataset(client, LEDGER, "Protected ledger — balances and account numbers. No agent reads this directly.")
    ensure_dataset(client, ANALYTICS, "Authorized views over the ledger. This is the only surface agents touch.")

    print("\n[2/5] Protected tables")
    load_table(client, f"{LEDGER}.bank_accounts", ACCOUNT_SCHEMA, ACCOUNTS)
    load_table(client, f"{LEDGER}.transactions", TRANSACTION_SCHEMA, [
        dict(zip([f.name for f in TRANSACTION_SCHEMA], row)) for row in TRANSACTIONS
    ])

    print("\n[3/5] Authorized views")
    ensure_view(client, f"{ANALYTICS}.transaction_facts", TRANSACTION_FACTS_SQL)
    ensure_view(client, f"{ANALYTICS}.account_funding_status", ACCOUNT_FUNDING_SQL)

    print("\n[4/5] View authorization on the protected dataset")
    authorize_views(client, [f"{ANALYTICS}.transaction_facts", f"{ANALYTICS}.account_funding_status"])

    print("\n[5/5] Per-view reader grants")
    grant_view_reader(client, f"{ANALYTICS}.transaction_facts", MONITOR_SA)
    grant_view_reader(client, f"{ANALYTICS}.transaction_facts", RECON_SA)
    grant_view_reader(client, f"{ANALYTICS}.account_funding_status", PAYMENTS_SA)

    print("\n=== Done. Prove it with: python test_finance_containment.py ===")


if __name__ == "__main__":
    main()

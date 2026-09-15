"""Three agents for a small-business finance product, each boxed in by IAM.

The design rule is the same one the clinical vertical uses: an agent's limits are a
property of its service account, not of its prompt. Nothing here checks whether an agent
is *allowed* to do something — it just tries, and Google Cloud refuses. If you delete the
rule gates below the agents still cannot exceed their grants; if you delete the grants,
no amount of prompting puts them back.

    agent-txn-monitor    reads transaction_facts        writes nothing, publishes nothing
    agent-payments       reads account_funding_status   publishes payment.requested
    agent-nightly-recon  reads transaction_facts        publishes recon.findings only

    python finance_agents.py        # runs all three against the seeded project
"""
import json
import sys
import time
import uuid

from google.cloud import bigquery, pubsub_v1

from gcp_auth import PROJECT_ID, agent_sa, get_impersonated_credentials

sys.stdout.reconfigure(encoding="utf-8")

FACTS_VIEW = f"`{PROJECT_ID}.finance_analytics.transaction_facts`"
FUNDING_VIEW = f"`{PROJECT_ID}.finance_analytics.account_funding_status`"

# Deterministic limits. An LLM proposes a payment; this decides whether it happens.
# Both numbers are policy, so they live in code where they can be reviewed and tested,
# not in a prompt where they can be argued with.
PER_PAYMENT_CAP_CENTS = 2_000_000
STRUCTURING_WINDOW_MINUTES = 15
STRUCTURING_COUNT = 3


def _bq(agent: str) -> bigquery.Client:
    return bigquery.Client(project=PROJECT_ID, credentials=get_impersonated_credentials(agent_sa(agent)))


def detect_findings(rows) -> list[dict]:
    """The monitor's judgement, separated from the query so it can be tested offline.

    Takes rows with txn_id / posted_at / amount_cents / counterparty attributes.
    """
    findings = []

    # Several large debits to one counterparty inside a short window is the classic
    # structuring shape: each one under the cap, the total well over it.
    by_counterparty: dict[str, list] = {}
    for row in rows:
        by_counterparty.setdefault(row.counterparty or "<unattributed>", []).append(row)
    for counterparty, group in by_counterparty.items():
        group.sort(key=lambda r: r.posted_at)
        for i in range(len(group) - STRUCTURING_COUNT + 1):
            window = group[i:i + STRUCTURING_COUNT]
            span_minutes = (window[-1].posted_at - window[0].posted_at).total_seconds() / 60
            if span_minutes <= STRUCTURING_WINDOW_MINUTES:
                total = sum(abs(r.amount_cents) for r in window)
                findings.append({
                    "type": "STRUCTURING_PATTERN",
                    "counterparty": counterparty,
                    "txn_ids": [r.txn_id for r in window],
                    "total_cents": total,
                    "detail": (f"{STRUCTURING_COUNT} debits totalling ${total / 100:,.2f} to "
                               f"{counterparty} within {span_minutes:.0f} minutes, each below the "
                               f"${PER_PAYMENT_CAP_CENTS / 100:,.0f} per-payment cap."),
                })
                break

    for row in rows:
        if row.counterparty is None:
            findings.append({
                "type": "UNATTRIBUTED_DEBIT",
                "txn_ids": [row.txn_id],
                "total_cents": abs(row.amount_cents),
                "detail": f"Debit of ${abs(row.amount_cents) / 100:,.2f} with no counterparty recorded.",
            })

    return findings


def run_transaction_monitor(business_id: str) -> dict:
    """Flags suspicious patterns over the facts view.

    Identity: agent-txn-monitor. It can see every transaction for the business and no
    account number, because the view it reads does not select those columns. It holds no
    publisher role on any topic, so a compromised monitor can raise a false alarm and
    nothing else.
    """
    client = _bq("txn-monitor")
    rows = list(client.query(
        f"""
        SELECT txn_id, posted_at, amount_cents, counterparty, category, status
        FROM {FACTS_VIEW}
        WHERE business_id = @business_id AND direction = 'debit'
        ORDER BY posted_at
        """,
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("business_id", "STRING", business_id)
        ]),
    ).result())

    findings = detect_findings(rows)

    print(f"[txn-monitor] {len(rows)} debits reviewed, {len(findings)} finding(s)")
    for finding in findings:
        print(f"    ⚠ {finding['type']}: {finding['detail']}")
    return {"success": True, "reviewed": len(rows), "findings": findings}


def run_payment_agent(account_id: str, amount_cents: int, counterparty: str) -> dict:
    """Requests an outbound payment, subject to a deterministic gate.

    Identity: agent-payments. It reads `account_funding_status`, which tells it whether
    the account is funded and which band the balance falls in — never the balance itself,
    the account number, or the routing number. It is the only identity in this vertical
    holding publisher on `payment.requested`.
    """
    client = _bq("payments")
    rows = list(client.query(
        f"SELECT is_funded, balance_band, daily_send_limit_cents FROM {FUNDING_VIEW} WHERE account_id = @account_id",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("account_id", "STRING", account_id)
        ]),
    ).result())
    if not rows:
        return {"success": False, "reason": "ACCOUNT_NOT_FOUND", "account_id": account_id}
    funding = rows[0]

    if amount_cents > PER_PAYMENT_CAP_CENTS:
        reason = (f"Exceeds the ${PER_PAYMENT_CAP_CENTS / 100:,.0f} per-payment cap. "
                  f"Blocked in code, not by model judgement.")
        print(f"[payments] ⊘ BLOCKED {account_id} → {counterparty}: {reason}")
        return {"success": False, "reason": "OVER_PER_PAYMENT_CAP", "detail": reason}

    if amount_cents > funding.daily_send_limit_cents:
        reason = f"Exceeds this account's daily send limit of ${funding.daily_send_limit_cents / 100:,.2f}."
        print(f"[payments] ⊘ BLOCKED {account_id} → {counterparty}: {reason}")
        return {"success": False, "reason": "OVER_DAILY_LIMIT", "detail": reason}

    if not funding.is_funded:
        print(f"[payments] ⊘ BLOCKED {account_id} → {counterparty}: account is not funded.")
        return {"success": False, "reason": "ACCOUNT_NOT_FUNDED"}

    payment_id = f"PMT-{uuid.uuid4().hex[:8].upper()}"
    payload = {
        "payment_id": payment_id,
        "account_id": account_id,
        "amount_cents": amount_cents,
        "counterparty": counterparty,
        "balance_band_at_request": funding.balance_band,
        "requested_by": agent_sa("payments"),
        "requested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    publisher = pubsub_v1.PublisherClient(credentials=get_impersonated_credentials(agent_sa("payments")))
    publisher.publish(
        publisher.topic_path(PROJECT_ID, "payment.requested"),
        json.dumps(payload).encode("utf-8"),
    ).result()
    print(f"[payments] ✓ {payment_id} requested: ${amount_cents / 100:,.2f} → {counterparty} "
          f"(balance band {funding.balance_band}, exact balance never read)")
    return {"success": True, "payment": payload}


def run_nightly_check(business_id: str) -> dict:
    """The overnight reconciliation pass. Reads everything, moves nothing.

    Identity: agent-nightly-recon. It holds reader on the facts view and publisher on
    `recon.findings` — and deliberately no publisher role on `payment.requested`. A batch
    job that runs unattended at 3am is the last thing that should be able to initiate a
    transfer, and here that isn't a policy, it's an absent IAM binding.
    """
    client = _bq("nightly-recon")
    rows = list(client.query(
        f"""
        SELECT txn_id, posted_at, amount_cents, direction, counterparty, category, status
        FROM {FACTS_VIEW}
        WHERE business_id = @business_id
        ORDER BY posted_at
        """,
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("business_id", "STRING", business_id)
        ]),
    ).result())

    inflow = sum(r.amount_cents for r in rows if r.amount_cents > 0 and r.status == "posted")
    outflow = -sum(r.amount_cents for r in rows if r.amount_cents < 0 and r.status == "posted")
    pending = [r.txn_id for r in rows if r.status != "posted"]

    # Same amount, same counterparty, same timestamp: a retry that got written twice.
    seen, duplicates = {}, []
    for row in rows:
        key = (row.posted_at, row.amount_cents, row.counterparty)
        if key in seen:
            duplicates.append({"txn_ids": [seen[key], row.txn_id], "amount_cents": row.amount_cents})
        seen[key] = row.txn_id

    report = {
        "business_id": business_id,
        "posted_inflow_cents": inflow,
        "posted_outflow_cents": outflow,
        "net_cents": inflow - outflow,
        "pending_txn_ids": pending,
        "suspected_duplicates": duplicates,
        "generated_by": agent_sa("nightly-recon"),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    publisher = pubsub_v1.PublisherClient(credentials=get_impersonated_credentials(agent_sa("nightly-recon")))
    publisher.publish(
        publisher.topic_path(PROJECT_ID, "recon.findings"),
        json.dumps(report).encode("utf-8"),
    ).result()

    print(f"[nightly-recon] {business_id}: in ${inflow / 100:,.2f} / out ${outflow / 100:,.2f} / "
          f"net ${(inflow - outflow) / 100:,.2f}")
    print(f"    {len(pending)} pending, {len(duplicates)} suspected duplicate(s)")
    return {"success": True, "report": report}


if __name__ == "__main__":
    print("=== Transaction monitoring ===")
    run_transaction_monitor("BIZ-4471")

    print("\n=== Payment requests ===")
    run_payment_agent("ACCT-1001", 45_000, "Gusto")
    run_payment_agent("ACCT-1001", 2_400_000, "Meridian Holdings LLC")
    run_payment_agent("ACCT-1002", 900_000, "Figma")

    print("\n=== Nightly reconciliation ===")
    run_nightly_check("BIZ-4471")
    run_nightly_check("BIZ-9021")

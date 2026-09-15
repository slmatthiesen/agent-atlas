"""The blast radius of every agent identity, probed live against Google Cloud.

This is the demo's central claim made checkable: for each (agent, resource) pair the
matrix declares what access *should* be, then actually attempts it under that agent's
own service account. A cell is green because Google Cloud allowed it or because Google
Cloud refused it — never because application code decided so.

`declared_matrix()` returns the grid without touching the network, which is what the UI
renders first. `probe_matrix()` fills in the live verdicts.
"""
from __future__ import annotations

import time

from google.api_core.exceptions import Forbidden, NotFound, PermissionDenied
from google.cloud import bigquery, pubsub_v1

from gcp_auth import PROJECT_ID, agent_sa, get_impersonated_credentials

ALLOWED = "ALLOWED"
DENIED = "DENIED"
ERROR = "ERROR"

# Resource kinds the prober knows how to reach.
BIGQUERY = "bigquery"
PUBSUB = "pubsub"


class Resource:
    """A thing an agent might touch, and how sensitive it is if they can."""

    def __init__(self, key, label, kind, sensitivity, target, probe_sql=None):
        self.key = key
        self.label = label
        self.kind = kind
        self.sensitivity = sensitivity  # "protected" | "derived" | "action"
        self.target = target
        self.probe_sql = probe_sql

    def as_dict(self):
        return {"key": self.key, "label": self.label, "kind": self.kind,
                "sensitivity": self.sensitivity, "target": self.target}


class Agent:
    def __init__(self, key, sa_name, label, purpose):
        self.key = key
        self.sa_name = sa_name
        self.label = label
        self.purpose = purpose

    def as_dict(self):
        return {"key": self.key, "label": self.label, "purpose": self.purpose,
                "identity": agent_sa(self.sa_name)}


def _bq_resource(key, label, sensitivity, table, columns="*"):
    return Resource(key, label, BIGQUERY, sensitivity, table,
                    probe_sql=f"SELECT {columns} FROM `{PROJECT_ID}.{table}` LIMIT 1")


FINANCE = {
    "key": "fintech",
    "label": "Apex Clearing",
    "tagline": "Money movement, where the identity is the control.",
    "resources": [
        _bq_resource("ledger.bank_accounts", "Bank accounts & balances", "protected",
                     "ledger.bank_accounts"),
        _bq_resource("ledger.transactions", "Raw transaction ledger", "protected",
                     "ledger.transactions"),
        _bq_resource("finance_analytics.transaction_facts", "Transaction facts (view)", "derived",
                     "finance_analytics.transaction_facts", columns="txn_id"),
        _bq_resource("finance_analytics.account_funding_status", "Funding status (view)", "derived",
                     "finance_analytics.account_funding_status", columns="account_id, is_funded"),
        Resource("payment.requested", "Request a payment", PUBSUB, "action", "payment.requested"),
        Resource("recon.findings", "Publish recon findings", PUBSUB, "action", "recon.findings"),
    ],
    "agents": [
        Agent("txn-monitor", "txn-monitor", "Transaction Monitor",
              "Watches the feed for anomalies. Has no reason to know whose account it is."),
        Agent("payments", "payments", "Payment Agent",
              "Moves money. Learns only whether an account is funded, never the balance."),
        Agent("nightly-recon", "nightly-recon", "Nightly Reconciliation",
              "Reads the whole feed and can report. Cannot move a cent."),
    ],
    # Anything omitted is expected DENIED — the default is no access.
    "expected_allowed": {
        ("txn-monitor", "finance_analytics.transaction_facts"),
        ("payments", "finance_analytics.account_funding_status"),
        ("payments", "payment.requested"),
        ("nightly-recon", "finance_analytics.transaction_facts"),
        ("nightly-recon", "recon.findings"),
    },
}

CLINICAL = {
    "key": "pharma",
    "label": "Meridian Clinical",
    "tagline": "Patient data an agent can act on without ever reading it.",
    "resources": [
        _bq_resource("clinical_records.patient_shipments", "Patient shipments (PHI)", "protected",
                     "clinical_records.patient_shipments"),
        _bq_resource("clinical_records.shipment_addresses", "Shipping addresses (view)", "derived",
                     "clinical_records.shipment_addresses", columns="record_id"),
        _bq_resource("analytics.lot_expiry_facts", "Lot expiry facts", "derived",
                     "analytics.lot_expiry_facts", columns="lot_number"),
        Resource("order.verified", "Publish a verified order", PUBSUB, "action", "order.verified"),
    ],
    "agents": [
        Agent("sales", "sales", "Sales Agent", "Quotes and pricing. Never sees a patient record."),
        Agent("ship", "ship", "Shipping Agent",
              "Ships to an address it can read, from a record it cannot."),
        Agent("reconcile", "reconcile", "Reconciliation Agent",
              "Works the lot-expiry facts, not the underlying clinical data."),
        Agent("verify", "verify", "Verification Agent", "Licence checks; publishes verified orders."),
    ],
    "expected_allowed": {
        ("ship", "clinical_records.shipment_addresses"),
        ("reconcile", "analytics.lot_expiry_facts"),
        ("verify", "order.verified"),
    },
}

VERTICALS = {v["key"]: v for v in (FINANCE, CLINICAL)}


def _expected(vertical, agent_key, resource_key):
    return ALLOWED if (agent_key, resource_key) in vertical["expected_allowed"] else DENIED


def declared_matrix(vertical_key: str) -> dict:
    """The grid as designed, with no network calls. Rendered before any probe runs."""
    vertical = VERTICALS[vertical_key]
    return {
        "vertical": vertical_key,
        "label": vertical["label"],
        "tagline": vertical["tagline"],
        "project": PROJECT_ID,
        "resources": [r.as_dict() for r in vertical["resources"]],
        "agents": [a.as_dict() for a in vertical["agents"]],
        "cells": [
            {"agent": a.key, "resource": r.key, "expected": _expected(vertical, a.key, r.key)}
            for a in vertical["agents"] for r in vertical["resources"]
        ],
    }


def _probe_bigquery(agent: Agent, resource: Resource) -> tuple[str, str]:
    client = bigquery.Client(project=PROJECT_ID,
                             credentials=get_impersonated_credentials(agent_sa(agent.sa_name)))
    try:
        rows = list(client.query(resource.probe_sql).result())
        return ALLOWED, f"{len(rows)} row(s) returned"
    except (Forbidden, PermissionDenied) as exc:
        return DENIED, exc.message
    except NotFound as exc:
        return ERROR, f"resource missing — run the seed scripts: {exc.message}"


def _probe_pubsub(agent: Agent, resource: Resource) -> tuple[str, str]:
    publisher = pubsub_v1.PublisherClient(
        credentials=get_impersonated_credentials(agent_sa(agent.sa_name)))
    try:
        publisher.publish(publisher.topic_path(PROJECT_ID, resource.target),
                          b'{"probe":true}').result(timeout=30)
        return ALLOWED, "publish accepted"
    except (Forbidden, PermissionDenied) as exc:
        return DENIED, getattr(exc, "message", str(exc))
    except NotFound as exc:
        return ERROR, f"topic missing — run bootstrap.py: {getattr(exc, 'message', exc)}"


def probe_cell(vertical_key: str, agent_key: str, resource_key: str) -> dict:
    """One live attempt under the agent's own identity."""
    vertical = VERTICALS[vertical_key]
    agent = next(a for a in vertical["agents"] if a.key == agent_key)
    resource = next(r for r in vertical["resources"] if r.key == resource_key)

    started = time.monotonic()
    try:
        outcome, detail = (_probe_bigquery if resource.kind == BIGQUERY else _probe_pubsub)(agent, resource)
    except Exception as exc:  # a broken identity should read as ERROR, not as a silent pass
        outcome, detail = ERROR, str(exc)[:300]

    expected = _expected(vertical, agent_key, resource_key)
    return {
        "agent": agent_key,
        "resource": resource_key,
        "expected": expected,
        "outcome": outcome,
        "holds": outcome == expected,
        "detail": detail,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


def probe_matrix(vertical_key: str) -> dict:
    """Run every cell. This is what the 'Run live' button calls."""
    grid = declared_matrix(vertical_key)
    cells = [probe_cell(vertical_key, c["agent"], c["resource"]) for c in grid["cells"]]
    grid["cells"] = cells
    grid["breaches"] = [c for c in cells if not c["holds"]]
    grid["holds"] = not grid["breaches"]
    grid["probed"] = True
    return grid

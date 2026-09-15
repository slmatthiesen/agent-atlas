import os
import sys
import subprocess
from google.cloud import bigquery
import google.oauth2.credentials

sys.stdout.reconfigure(encoding='utf-8')

from gcp_auth import PROJECT_ID  # resolves from GCP_PROJECT or ADC

token = subprocess.check_output("gcloud auth print-access-token", shell=True, text=True).strip()
creds = google.oauth2.credentials.Credentials(token)
bq_client = bigquery.Client(project=PROJECT_ID, credentials=creds)

print("=== Setting BigQuery Dataset Access & Authorizing View ===")

# 1. Authorize view 'shipment_addresses' on dataset 'clinical_records'
dataset_ref = bq_client.dataset("clinical_records")
dataset = bq_client.get_dataset(dataset_ref)

entries = list(dataset.access_entries)
agent_ship_sa = f"agent-ship@{PROJECT_ID}.iam.gserviceaccount.com"

# Remove dataset-level READER permission for agent-ship on clinical_records if present
# (Access to clinical_records MUST be restricted to the authorized view only)
entries = [e for e in entries if getattr(e, 'entity_id', None) != agent_ship_sa]

view_access_entry = bigquery.AccessEntry(
    role=None,
    entity_type="view",
    entity_id={
        "projectId": PROJECT_ID,
        "datasetId": "clinical_records",
        "tableId": "shipment_addresses"
    }
)

already_authorized = any(
    e.entity_type == "view" and isinstance(e.entity_id, dict) and e.entity_id.get("tableId") == "shipment_addresses"
    for e in entries
)

if not already_authorized:
    entries.append(view_access_entry)

dataset.access_entries = entries
bq_client.update_dataset(dataset, ["access_entries"])
print("✅ Authorized View 'shipment_addresses' on dataset 'clinical_records'!")

# Grant agent-ship dataViewer ON THE VIEW ONLY via table-level IAM policy
view_table = bq_client.get_table(f"{PROJECT_ID}.clinical_records.shipment_addresses")
policy = bq_client.get_iam_policy(view_table)
has_grant = any(
    b.get("role") == "roles/bigquery.dataViewer" and f"serviceAccount:{agent_ship_sa}" in b.get("members", [])
    for b in policy.bindings
)
if not has_grant:
    policy.bindings.append({
        "role": "roles/bigquery.dataViewer",
        "members": [f"serviceAccount:{agent_ship_sa}"]
    })
    bq_client.set_iam_policy(view_table, policy)
print("✅ Granted table-level dataViewer on view 'shipment_addresses' to agent-ship!")

# 2. Grant agent-reconcile READER on dataset 'analytics'
analytics_ref = bq_client.dataset("analytics")
analytics_dataset = bq_client.get_dataset(analytics_ref)

analytics_entries = list(analytics_dataset.access_entries)
reconcile_sa = f"agent-reconcile@{PROJECT_ID}.iam.gserviceaccount.com"

reconcile_access_entry = bigquery.AccessEntry(
    role="READER",
    entity_type="userByEmail",
    entity_id=reconcile_sa
)

already_granted_reconcile = any(
    getattr(e, 'entity_id', None) == reconcile_sa for e in analytics_entries
)

if not already_granted_reconcile:
    analytics_entries.append(reconcile_access_entry)
    analytics_dataset.access_entries = analytics_entries
    bq_client.update_dataset(analytics_dataset, ["access_entries"])
    print("✅ Granted READER on dataset 'analytics' to agent-reconcile!")

print("=== BigQuery Dataset Authorization Complete! ===")

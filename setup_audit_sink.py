import os
import sys
import subprocess
import time
import json
from google.cloud import bigquery
from google.api_core.exceptions import Conflict
import google.oauth2.credentials

sys.stdout.reconfigure(encoding='utf-8')

from gcp_auth import PROJECT_ID  # resolves from GCP_PROJECT or ADC

token = subprocess.check_output("gcloud auth print-access-token", shell=True, text=True).strip()
creds = google.oauth2.credentials.Credentials(token)

print(f"=== Setting up Phase 4 Audit Logging & BigQuery Log Router Sink ({PROJECT_ID}) ===")

# 1. Enable Data Access Audit Logs for BigQuery & Datastore in Project IAM Policy
print("\n--- 1. Enabling Data Access Audit Logs in Project IAM Policy ---")

import shutil

gcloud_bin = shutil.which("gcloud") or "gcloud.cmd"

policy_json_str = subprocess.check_output([gcloud_bin, "projects", "get-iam-policy", PROJECT_ID, "--format=json"], text=True)
policy = json.loads(policy_json_str)

audit_configs = [
    {
        "service": "bigquery.googleapis.com",
        "auditLogConfigs": [
            {"logType": "DATA_READ"},
            {"logType": "DATA_WRITE"},
            {"logType": "ADMIN_READ"}
        ]
    },
    {
        "service": "datastore.googleapis.com",
        "auditLogConfigs": [
            {"logType": "DATA_READ"},
            {"logType": "DATA_WRITE"},
            {"logType": "ADMIN_READ"}
        ]
    }
]

policy["auditConfigs"] = audit_configs

# Write back updated IAM policy
tmp_policy_path = os.path.join(os.path.dirname(__file__), "tmp_policy.json")
with open(tmp_policy_path, "w", encoding="utf-8") as f:
    json.dump(policy, f, indent=2)

try:
    subprocess.check_output([gcloud_bin, "projects", "set-iam-policy", PROJECT_ID, tmp_policy_path], text=True)
    print("✅ Successfully updated project IAM auditConfigs for BigQuery & Datastore!")
finally:
    if os.path.exists(tmp_policy_path):
        os.remove(tmp_policy_path)

bq_client = bigquery.Client(project=PROJECT_ID, credentials=creds)

# Same gap as the clinical datasets: the sink's destination has to exist first.
audit_dataset = bigquery.Dataset(f"{PROJECT_ID}.agent_audit")
audit_dataset.location = "US"
audit_dataset.description = "Admin Activity and Data Access logs routed from Cloud Logging."
try:
    bq_client.create_dataset(audit_dataset)
    print("Created dataset: agent_audit")
except Conflict:
    print("Dataset already exists: agent_audit")

# 2. Create Log Router Sink pointing to BigQuery dataset agent_audit
print("\n--- 2. Creating Log Router Sink -> BigQuery dataset 'agent_audit' ---")
sink_name = "agent-audit-sink"
destination = f"bigquery.googleapis.com/projects/{PROJECT_ID}/datasets/agent_audit"
log_filter = 'logName:"cloudaudit.googleapis.com" AND (protoPayload.serviceName="bigquery.googleapis.com" OR protoPayload.serviceName="datastore.googleapis.com")'

try:
    existing_sink_json = subprocess.check_output(
        [gcloud_bin, "logging", "sinks", "describe", sink_name, "--format=json"],
        text=True, stderr=subprocess.DEVNULL
    )
    existing_sink = json.loads(existing_sink_json)
    writer_identity = existing_sink.get("writerIdentity")
    print(f"Sink '{sink_name}' already exists. Writer identity: {writer_identity}")
except subprocess.CalledProcessError:
    sink_json_out = subprocess.check_output(
        [gcloud_bin, "logging", "sinks", "create", sink_name, destination, f"--log-filter={log_filter}", "--format=json"],
        text=True
    )
    created_sink = json.loads(sink_json_out)
    writer_identity = created_sink.get("writerIdentity")
    print(f"✅ Created Log Router sink '{sink_name}'. Writer identity: {writer_identity}")

# 3. Grant Writer Identity permissions to BigQuery dataset agent_audit
print("\n--- 3. Granting Writer Identity permissions on BigQuery dataset 'agent_audit' ---")
dataset_ref = bq_client.dataset("agent_audit")
dataset = bq_client.get_dataset(dataset_ref)

entries = list(dataset.access_entries)

# Extract service account email from writerIdentity e.g. serviceAccount:p12345-1234@gcp-sa-logging.iam.gserviceaccount.com
sa_email = writer_identity.replace("serviceAccount:", "")

already_granted = any(
    getattr(e, 'entity_id', None) == sa_email for e in entries
)

if not already_granted:
    writer_entry = bigquery.AccessEntry(
        role="WRITER",
        entity_type="userByEmail",
        entity_id=sa_email
    )
    entries.append(writer_entry)
    dataset.access_entries = entries
    bq_client.update_dataset(dataset, ["access_entries"])
    print(f"✅ Granted WRITER role on dataset 'agent_audit' to log sink writer '{sa_email}'!")
else:
    print(f"Log sink writer '{sa_email}' already has access to dataset 'agent_audit'.")

print("\n=== Phase 4 Audit Logging & Sink Setup Complete! ===")

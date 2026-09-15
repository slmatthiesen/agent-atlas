import os
import sys
import subprocess
from google.cloud import bigquery
from google.auth import impersonated_credentials
import google.oauth2.credentials
from google.api_core.exceptions import Forbidden, PermissionDenied

sys.stdout.reconfigure(encoding='utf-8')

from gcp_auth import PROJECT_ID  # resolves from GCP_PROJECT or ADC

print(f"=== Phase 2 Keystone Test: IAM Containment Verification ({PROJECT_ID}) ===")

# Base user credentials from gcloud session
token = subprocess.check_output("gcloud auth print-access-token", shell=True, text=True).strip()
base_creds = google.oauth2.credentials.Credentials(token)

def get_impersonated_bq_client(sa_email):
    target_scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    target_credentials = impersonated_credentials.Credentials(
        source_credentials=base_creds,
        target_principal=sa_email,
        target_scopes=target_scopes,
    )
    return bigquery.Client(project=PROJECT_ID, credentials=target_credentials)

# -------------------------------------------------------------
# TEST 1 (The Keystone Assertion):
# agent-sales MUST BE DENIED (403) when attempting to read clinical_records.patient_shipments
# -------------------------------------------------------------
sales_sa = f"agent-sales@{PROJECT_ID}.iam.gserviceaccount.com"
print(f"\n[TEST 1] Testing unauthorized access by '{sales_sa}' on protected BigQuery table 'clinical_records.patient_shipments'...")

sales_bq = get_impersonated_bq_client(sales_sa)
query = f"SELECT * FROM `{PROJECT_ID}.clinical_records.patient_shipments` LIMIT 1"

try:
    query_job = sales_bq.query(query)
    results = list(query_job.result())
    print("❌ SECURITY FAILURE! agent-sales was able to read protected patient records!")
    print("ASSERTION FAILED: Build must fail because containment was breached.")
    exit(1)
except (Forbidden, PermissionDenied) as e:
    print(f"✅ SUCCESS! IAM Backstop holds! Access was DENIED with 403 Forbidden.")
    print(f"   Exact GCP Error Payload: {e.message}")

# -------------------------------------------------------------
# TEST 2:
# agent-ship MUST BE DENIED (403) when querying raw clinical_records.patient_shipments
# -------------------------------------------------------------
ship_sa = f"agent-ship@{PROJECT_ID}.iam.gserviceaccount.com"
print(f"\n[TEST 2] Testing raw PHI access by '{ship_sa}' on 'clinical_records.patient_shipments'...")

ship_bq = get_impersonated_bq_client(ship_sa)

try:
    query_job = ship_bq.query(query)
    results = list(query_job.result())
    print("❌ SECURITY FAILURE! agent-ship read underlying raw PHI table!")
    exit(1)
except (Forbidden, PermissionDenied) as e:
    print(f"✅ SUCCESS! agent-ship is denied raw PHI access as designed (403).")

# -------------------------------------------------------------
# TEST 3:
# agent-ship MUST SUCCEED (200) when querying Authorized View clinical_records.shipment_addresses
# -------------------------------------------------------------
print(f"\n[TEST 3] Testing authorized access by '{ship_sa}' on Authorized View 'clinical_records.shipment_addresses'...")
view_query = f"SELECT record_id, recipient_name, delivery_street, delivery_city FROM `{PROJECT_ID}.clinical_records.shipment_addresses` LIMIT 5"

try:
    query_job = ship_bq.query(view_query)
    results = list(query_job.result())
    print(f"✅ SUCCESS! agent-ship successfully queried Authorized View (returned {len(results)} rows).")
    for row in results:
        print(f"   View Record: {row.record_id} | Recipient: {row.recipient_name} | City: {row.delivery_city}")
except Exception as e:
    print(f"❌ UNEXPECTED FAILURE: agent-ship should have access to Authorized View: {e}")
    exit(1)

# -------------------------------------------------------------
# TEST 4:
# agent-reconcile MUST SUCCEED (200) on analytics dataset
# -------------------------------------------------------------
reconcile_sa = f"agent-reconcile@{PROJECT_ID}.iam.gserviceaccount.com"
print(f"\n[TEST 4] Testing analytical query by '{reconcile_sa}' on 'analytics.lot_expiry_facts'...")
reconcile_bq = get_impersonated_bq_client(reconcile_sa)
analytics_query = f"SELECT lot_number, sku_name, current_qty, expiration_date FROM `{PROJECT_ID}.analytics.lot_expiry_facts` WHERE expiration_date < '2026-09-01'"

try:
    query_job = reconcile_bq.query(analytics_query)
    results = list(query_job.result())
    print(f"✅ SUCCESS! agent-reconcile queried analytics dataset (found {len(results)} expiring lots).")
    for row in results:
        print(f"   Expiring Lot: {row.lot_number} | SKU: {row.sku_name} | Expires: {row.expiration_date}")
except Exception as e:
    print(f"❌ UNEXPECTED FAILURE: agent-reconcile should have read access to analytics dataset: {e}")
    exit(1)

print("\n=== ALL IAM CONTAINMENT TESTS PASSED PERFECTLY! ===")

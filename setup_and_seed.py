import os
import time
import subprocess
from google.cloud import bigquery
from google.cloud import firestore
from google.cloud import pubsub_v1
import google.oauth2.credentials
from google.api_core.exceptions import AlreadyExists, Conflict, NotFound

from gcp_auth import PROJECT_ID  # resolves from GCP_PROJECT or ADC
REGION = "us-central1"

print(f"=== Starting Meridian Infrastructure & Synthetic Data Seeding for Project: {PROJECT_ID} ===")

# Fetch token directly from gcloud CLI authentication
print("Fetching OAuth2 credentials from active gcloud session...")
token = subprocess.check_output("gcloud auth print-access-token", shell=True, text=True).strip()
credentials = google.oauth2.credentials.Credentials(token)

# 1. Pub/Sub Topics & Subscriptions
print("\n--- 1. Setting up Pub/Sub Topics & Subscriptions ---")
publisher = pubsub_v1.PublisherClient(credentials=credentials)
subscriber = pubsub_v1.SubscriberClient(credentials=credentials)

topics = ["order.verified", "order.packed", "reconcile.recommendations"]
subs = {
    "order.verified-sub": "order.verified",
    "order.packed-sub": "order.packed"
}

for topic_id in topics:
    topic_path = publisher.topic_path(PROJECT_ID, topic_id)
    try:
        publisher.create_topic(request={"name": topic_path})
        print(f"Created topic: {topic_id}")
    except AlreadyExists:
        print(f"Topic already exists: {topic_id}")

for sub_id, topic_id in subs.items():
    topic_path = publisher.topic_path(PROJECT_ID, topic_id)
    sub_path = subscriber.subscription_path(PROJECT_ID, sub_id)
    try:
        subscriber.create_subscription(request={"name": sub_path, "topic": topic_path})
        print(f"Created subscription: {sub_id} on {topic_id}")
    except AlreadyExists:
        print(f"Subscription already exists: {sub_id}")

# 2. BigQuery Tables & Authorized Views
print("\n--- 2. Setting up BigQuery Tables & Authorized Views ---")
bq_client = bigquery.Client(project=PROJECT_ID, credentials=credentials)

# The datasets came pre-provisioned on the original lab project, so nothing created
# them here. On a fresh project the table writes below 404 without this.
for dataset_id, description in {
    "clinical_records": "Patient shipment records. PHI — reachable only via authorized view.",
    "analytics": "Non-PHI derived facts safe for broad agent access.",
}.items():
    dataset = bigquery.Dataset(f"{PROJECT_ID}.{dataset_id}")
    dataset.location = "US"
    dataset.description = description
    try:
        bq_client.create_dataset(dataset)
        print(f"Created dataset: {dataset_id}")
    except Conflict:
        print(f"Dataset already exists: {dataset_id}")

# 2a. Protected Table: clinical_records.patient_shipments
patient_shipments_table_id = f"{PROJECT_ID}.clinical_records.patient_shipments"
patient_schema = [
    bigquery.SchemaField("record_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("clinic_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("patient_name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("medical_condition", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("prescription_rx_number", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("recipient_name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("delivery_street", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("delivery_city", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("delivery_state", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("delivery_zip", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("is_synthetic", "STRING", mode="REQUIRED"),
]

table = bigquery.Table(patient_shipments_table_id, schema=patient_schema)
try:
    table = bq_client.create_table(table)
    print(f"Created table: {patient_shipments_table_id}")
except Conflict:
    print(f"Table already exists: {patient_shipments_table_id}")

# Seed synthetic patient shipment records
synthetic_patients = [
    {
        "record_id": "REC-9001",
        "clinic_id": "CLINIC-4471",
        "patient_name": "SYNTHETIC_JOHN_DOE",
        "medical_condition": "Type 1 Diabetes Mellitus",
        "prescription_rx_number": "RX-882103",
        "recipient_name": "Dr. Sarah Jenkins / Clinic 4471 Receiving",
        "delivery_street": "104 Healthcare Boulevard, Suite 200",
        "delivery_city": "Austin",
        "delivery_state": "TX",
        "delivery_zip": "78701",
        "is_synthetic": "SYNTHETIC_DATA_DO_NOT_USE_REAL_PHI"
    },
    {
        "record_id": "REC-9002",
        "clinic_id": "CLINIC-4471",
        "patient_name": "SYNTHETIC_JANE_SMITH",
        "medical_condition": "Severe Acute Asthma",
        "prescription_rx_number": "RX-882104",
        "recipient_name": "Dr. Sarah Jenkins / Clinic 4471 Receiving",
        "delivery_street": "104 Healthcare Boulevard, Suite 200",
        "delivery_city": "Austin",
        "delivery_state": "TX",
        "delivery_zip": "78701",
        "is_synthetic": "SYNTHETIC_DATA_DO_NOT_USE_REAL_PHI"
    },
    {
        "record_id": "REC-9003",
        "clinic_id": "CLINIC-9021",
        "patient_name": "SYNTHETIC_ALICE_RIVER",
        "medical_condition": "Post-Op Anesthesia Recovery",
        "prescription_rx_number": "RX-991002",
        "recipient_name": "Metro Surgical Center Receiving Dock B",
        "delivery_street": "500 Metro Parkway",
        "delivery_city": "Dallas",
        "delivery_state": "TX",
        "delivery_zip": "75201",
        "is_synthetic": "SYNTHETIC_DATA_DO_NOT_USE_REAL_PHI"
    }
]

errors = bq_client.insert_rows_json(patient_shipments_table_id, synthetic_patients)
if not errors:
    print(f"Seeded {len(synthetic_patients)} synthetic records into {patient_shipments_table_id}")
else:
    print(f"Errors seeding {patient_shipments_table_id}: {errors}")

# 2b. Authorized View: clinical_records.shipment_addresses
view_id = f"{PROJECT_ID}.clinical_records.shipment_addresses"
view_sql = f"""
SELECT
  record_id,
  clinic_id,
  recipient_name,
  delivery_street,
  delivery_city,
  delivery_state,
  delivery_zip,
  is_synthetic
FROM `{patient_shipments_table_id}`
"""

view = bigquery.Table(view_id)
view.view_query = view_sql
try:
    view = bq_client.create_table(view)
    print(f"Created authorized view: {view_id}")
except Conflict:
    print(f"Authorized view already exists: {view_id}")

# 2c. Table: analytics.lot_expiry_facts
lot_facts_table_id = f"{PROJECT_ID}.analytics.lot_expiry_facts"
lot_schema = [
    bigquery.SchemaField("lot_number", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("sku", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("sku_name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("current_qty", "INTEGER", mode="REQUIRED"),
    bigquery.SchemaField("expiration_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("storage_temp_c", "FLOAT", mode="REQUIRED"),
    bigquery.SchemaField("reorder_point", "INTEGER", mode="REQUIRED"),
]

lot_table = bigquery.Table(lot_facts_table_id, schema=lot_schema)
try:
    lot_table = bq_client.create_table(lot_table)
    print(f"Created table: {lot_facts_table_id}")
except Conflict:
    print(f"Table already exists: {lot_facts_table_id}")

synthetic_lots = [
    {
        "lot_number": "LOT-INS-2026A",
        "sku": "SKU-INSULIN-01",
        "sku_name": "Insulin Glargine 100U/ml (Cold Chain Required)",
        "current_qty": 45,
        "expiration_date": "2026-08-25",  # Expiring soon!
        "storage_temp_c": 4.0,
        "reorder_point": 100
    },
    {
        "lot_number": "LOT-SAL-2026B",
        "sku": "SKU-SALINE-02",
        "sku_name": "0.9% Sodium Chloride IV 500ml",
        "current_qty": 1200,
        "expiration_date": "2027-05-15",
        "storage_temp_c": 20.0,
        "reorder_point": 300
    },
    {
        "lot_number": "LOT-ANE-2026C",
        "sku": "SKU-ANESTHETIC-03",
        "sku_name": "Propofol Injectable 10mg/ml (Controlled Class B)",
        "current_qty": 12,  # Below reorder point!
        "expiration_date": "2026-11-30",
        "storage_temp_c": 15.0,
        "reorder_point": 50
    }
]

errors = bq_client.insert_rows_json(lot_facts_table_id, synthetic_lots)
if not errors:
    print(f"Seeded {len(synthetic_lots)} lot facts into {lot_facts_table_id}")
else:
    print(f"Errors seeding {lot_facts_table_id}: {errors}")


# 3. Firestore Collections
print("\n--- 3. Setting up Firestore Collections ---")
db = firestore.Client(project=PROJECT_ID, credentials=credentials)

# 3a. Catalog
catalog_data = {
    "SKU-INSULIN-01": {
        "sku": "SKU-INSULIN-01",
        "name": "Insulin Glargine 100U/ml",
        "restricted_license_required": True,
        "cold_chain_required": True,
        "unit_price": 85.50,
        "lot_tracked": True,
        "description": "Long-acting human insulin analog. License check and cold chain mandatory."
    },
    "SKU-SALINE-02": {
        "sku": "SKU-SALINE-02",
        "name": "0.9% Sodium Chloride IV 500ml",
        "restricted_license_required": False,
        "cold_chain_required": False,
        "unit_price": 12.00,
        "lot_tracked": True,
        "description": "Standard sterile intravenous saline solution."
    },
    "SKU-ANESTHETIC-03": {
        "sku": "SKU-ANESTHETIC-03",
        "name": "Propofol Injectable 10mg/ml",
        "restricted_license_required": True,
        "cold_chain_required": False,
        "unit_price": 140.00,
        "lot_tracked": True,
        "description": "Class B controlled anesthetic agent. Strict DEA/Clinic license gating."
    }
}

for sku_id, item in catalog_data.items():
    db.collection("catalog").document(sku_id).set(item)
print(f"Seeded catalog ({len(catalog_data)} items)")

# 3b. Clinics
clinics_data = {
    "CLINIC-4471": {
        "clinic_id": "CLINIC-4471",
        "name": "Austin Regional Health Center",
        "license_number": "TX-MED-4471-ACTIVE",
        "license_status": "ACTIVE",
        "licensed_for_restricted_items": True,
        "address": {
            "street": "104 Healthcare Boulevard, Suite 200",
            "city": "Austin",
            "state": "TX",
            "zip": "78701"
        }
    },
    "CLINIC-9021": {
        "clinic_id": "CLINIC-9021",
        "name": "Metro Surgical Center (Expired License Test)",
        "license_number": "TX-MED-9021-EXPIRED",
        "license_status": "EXPIRED",
        "licensed_for_restricted_items": False,
        "address": {
            "street": "500 Metro Parkway",
            "city": "Dallas",
            "state": "TX",
            "zip": "75201"
        }
    }
}

for clinic_id, clinic_item in clinics_data.items():
    db.collection("clinics").document(clinic_id).set(clinic_item)
print(f"Seeded clinics ({len(clinics_data)} clinics)")

# 3c. Inventory Lots
lots_data = {
    "LOT-INS-2026A": {
        "lot_number": "LOT-INS-2026A",
        "sku": "SKU-INSULIN-01",
        "available_qty": 45,
        "expiration_date": "2026-08-25",
        "cold_chain": True
    },
    "LOT-SAL-2026B": {
        "lot_number": "LOT-SAL-2026B",
        "sku": "SKU-SALINE-02",
        "available_qty": 1200,
        "expiration_date": "2027-05-15",
        "cold_chain": False
    }
}

for lot_id, lot_item in lots_data.items():
    db.collection("inventory_lots").document(lot_id).set(lot_item)
print(f"Seeded inventory_lots ({len(lots_data)} lots)")

print("\n=== Setup and Synthetic Seeding Complete! ===")

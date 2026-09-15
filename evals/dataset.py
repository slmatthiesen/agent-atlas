"""Fixed evaluation set for the Meridian agent workloads.

Grading is deterministic — exact field match for extraction, required/forbidden
substrings for grounding, exact label for gating. No model grades another model,
so a reported score is reproducible by anyone who reruns the harness.
"""

# Catalog and clinic facts the agents operate against, mirrored from the seeded
# Firestore data so eval prompts and production prompts describe the same world.
CATALOG = {
    "SKU-INSULIN-01": {"name": "Insulin Glargine 100U/ml", "restricted": True, "cold_chain": True},
    "SKU-SALINE-02": {"name": "Sterile Saline 0.9%", "restricted": False, "cold_chain": False},
    "SKU-ANESTHETIC-03": {"name": "Propofol Injectable 10mg/ml", "restricted": True, "cold_chain": True},
}

CLINICS = {
    "CLINIC-4471": {"name": "Austin Regional Health Center", "license_status": "ACTIVE",
                    "licensed_for_restricted_items": True},
    "CLINIC-9021": {"name": "Metro Surgical Center", "license_status": "EXPIRED",
                    "licensed_for_restricted_items": False},
}

# ---------------------------------------------------------------------------
# Task 1 — order intent extraction (the voice-frontdoor workload)
# ---------------------------------------------------------------------------
INTENT_EXTRACTION = [
    {
        "id": "intent-01",
        "utterance": "Order 10 units of Insulin Glargine for Austin Regional Health Center Clinic 4471",
        "expected": {"clinic_id": "CLINIC-4471", "sku": "SKU-INSULIN-01", "quantity": 10},
    },
    {
        "id": "intent-02",
        "utterance": "This is Metro Surgical, we need twenty five units of Propofol",
        "expected": {"clinic_id": "CLINIC-9021", "sku": "SKU-ANESTHETIC-03", "quantity": 25},
    },
    {
        "id": "intent-03",
        "utterance": "Hi, clinic four four seven one here, send over five boxes of sterile saline please",
        "expected": {"clinic_id": "CLINIC-4471", "sku": "SKU-SALINE-02", "quantity": 5},
    },
    {
        "id": "intent-04",
        # Distractor: 9021 is the clinic, 100 is a product strength, 12 is the quantity.
        "utterance": "Clinic 9021 needs 12 vials of the 100 unit per ml insulin",
        "expected": {"clinic_id": "CLINIC-9021", "sku": "SKU-INSULIN-01", "quantity": 12},
    },
    {
        "id": "intent-05",
        "utterance": "Austin Regional needs a resupply of anesthetic, thirty units",
        "expected": {"clinic_id": "CLINIC-4471", "sku": "SKU-ANESTHETIC-03", "quantity": 30},
    },
    {
        "id": "intent-06",
        # No quantity stated; the documented default is 1.
        "utterance": "Metro Surgical Center would like to order saline",
        "expected": {"clinic_id": "CLINIC-9021", "sku": "SKU-SALINE-02", "quantity": 1},
    },
    {
        "id": "intent-07",
        "utterance": "Put in an order for 8 units of Glargine going to 4471",
        "expected": {"clinic_id": "CLINIC-4471", "sku": "SKU-INSULIN-01", "quantity": 8},
    },
    {
        "id": "intent-08",
        # Correction mid-utterance — the final stated quantity wins.
        "utterance": "We need 15, sorry, make that 18 units of Propofol for Metro Surgical",
        "expected": {"clinic_id": "CLINIC-9021", "sku": "SKU-ANESTHETIC-03", "quantity": 18},
    },
    {
        "id": "intent-09",
        "utterance": "Saline order, forty units, Austin Regional Health Center",
        "expected": {"clinic_id": "CLINIC-4471", "sku": "SKU-SALINE-02", "quantity": 40},
    },
    {
        "id": "intent-10",
        # Brand-adjacent phrasing for the same molecule.
        "utterance": "Clinic 4471 requesting 6 units long acting insulin",
        "expected": {"clinic_id": "CLINIC-4471", "sku": "SKU-INSULIN-01", "quantity": 6},
    },
    {
        "id": "intent-11",
        "utterance": "Metro Surgical, clinic nine zero two one, three units of propofol injectable",
        "expected": {"clinic_id": "CLINIC-9021", "sku": "SKU-ANESTHETIC-03", "quantity": 3},
    },
    {
        "id": "intent-12",
        "utterance": "Need 100 units of saline at Austin Regional as soon as possible",
        "expected": {"clinic_id": "CLINIC-4471", "sku": "SKU-SALINE-02", "quantity": 100},
    },
]

# ---------------------------------------------------------------------------
# Task 2 — license gating decision
#
# Production runs this as deterministic code. The eval exists to quantify what is
# lost by letting a model make the call instead, which is the argument for keeping
# the compliance boundary out of the model.
# ---------------------------------------------------------------------------
LICENSE_GATE = [
    {"id": "gate-01", "clinic_id": "CLINIC-4471", "sku": "SKU-INSULIN-01", "expected": "APPROVE"},
    {"id": "gate-02", "clinic_id": "CLINIC-9021", "sku": "SKU-INSULIN-01", "expected": "REJECT"},
    {"id": "gate-03", "clinic_id": "CLINIC-9021", "sku": "SKU-SALINE-02", "expected": "APPROVE"},
    {"id": "gate-04", "clinic_id": "CLINIC-4471", "sku": "SKU-ANESTHETIC-03", "expected": "APPROVE"},
    {"id": "gate-05", "clinic_id": "CLINIC-9021", "sku": "SKU-ANESTHETIC-03", "expected": "REJECT"},
    {"id": "gate-06", "clinic_id": "CLINIC-4471", "sku": "SKU-SALINE-02", "expected": "APPROVE"},
]

# ---------------------------------------------------------------------------
# Task 3 — RAG grounding over the SOP corpus
#
# `must_include` are facts a correct answer has to state. `must_not_include`
# catches the specific hallucinations this corpus invites.
# ---------------------------------------------------------------------------
RAG_GROUNDING = [
    {
        "id": "rag-01",
        "question": "What temperature range must Insulin Glargine be stored at?",
        "must_include": [["2°c", "2 c", "2c"], ["8°c", "8 c", "8c"]],
        "must_not_include": [],
    },
    {
        "id": "rag-02",
        "question": "How long can a temperature excursion above 8 degrees last before the lot must be quarantined?",
        "must_include": [["60", "sixty"]],
        "must_not_include": [],
    },
    {
        "id": "rag-03",
        "question": "Which carrier is contracted for refrigerated biologics?",
        "must_include": [["medexpress"]],
        "must_not_include": [],
    },
    {
        "id": "rag-04",
        "question": "What happens to an order if the clinic's DEA registration has expired?",
        "must_include": [["reject", "block", "hard-block"]],
        "must_not_include": [],
    },
    {
        "id": "rag-05",
        "question": "What allocation order does the warehouse use when several lots could fill an order?",
        "must_include": [["nearest", "first-expiring", "first expiring", "fefo", "earliest"]],
        "must_not_include": [],
    },
    {
        "id": "rag-06",
        "question": "How often must the shipment temperature logger take a reading?",
        "must_include": [["15", "fifteen"]],
        "must_not_include": [],
    },
    {
        "id": "rag-07",
        # Out of scope: a correct system declines rather than inventing a policy.
        "question": "What is Meridian's refund policy for opened vials?",
        "must_include": [["not", "no ", "does not", "cannot", "unable"]],
        "must_not_include": ["30 day", "30-day", "full refund"],
    },
    {
        "id": "rag-08",
        "question": "Can a lot that was accidentally frozen be returned to sellable stock?",
        "must_include": [["no", "not", "destroy", "non-viable"]],
        "must_not_include": [],
    },
]

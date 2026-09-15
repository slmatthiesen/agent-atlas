# Meridian Clinical Supply — Controlled Substance & License Verification SOP

> Synthetic sample corpus authored for this demo. Modeled on general controlled-substance
> distribution practice; not a reproduction of any real regulatory publication.

## Section 1 — Purpose

This procedure defines how Meridian verifies that a receiving clinic is licensed to
take delivery of restricted pharmaceutical products before any order is released to
the warehouse.

## Section 2 — Restricted Product Classification

A catalog SKU is restricted when it carries the `restricted_license_required` flag.
Restricted classes include controlled substances and certain refrigerated biologics.
Anesthetic agents such as Propofol (SKU-ANESTHETIC-03) are restricted. Non-restricted
consumables such as Sterile Saline (SKU-SALINE-02) are exempt from license gating.

## Section 3 — License Verification Gate

Before a restricted order advances past verification, the clinic record is read from
the operational clinic registry and two conditions must both hold:

1. `license_status` equals `ACTIVE` — the clinic's DEA registration is current
2. `licensed_for_restricted_items` is true

If either condition fails — most commonly an expired DEA registration — the order is
rejected and marked `REJECTED_LICENSE_EXPIRED`. Rejection is terminal for that order;
it cannot be retried without a fresh DEA license record. A clinic whose DEA
registration has lapsed may not receive any restricted product until the registration
is renewed and the registry record is updated.

## Section 4 — Deterministic Enforcement

License gating is implemented as deterministic application code, not as a model
decision. A language model may summarize or explain a rejection to an operator, but
it never decides the outcome. This keeps the compliance boundary auditable and makes
the gate immune to prompt injection.

## Section 5 — Worked Examples

Austin Regional Health Center, clinic identifier CLINIC-4471, holds DEA registration
TX-MED-4471 in ACTIVE status with restricted-item authorization, and is therefore
cleared for restricted orders including refrigerated biologics.

Metro Surgical Center, clinic identifier CLINIC-9021, holds DEA registration
TX-MED-9021 in EXPIRED status. Restricted orders for this clinic are hard-blocked at
the verification gate before warehouse picking begins. The clinic may still receive
non-restricted consumables such as sterile saline.

## Section 6 — Segregation of Data Access

The verification agent reads only the clinic registry. It holds no permission on
patient-level clinical records. Downstream agents that require a delivery address
read it through a restricted authorized view exposing address fields only, never the
underlying patient table. Access separation is enforced by IAM at the data layer
rather than by application convention.

## Section 7 — Audit Retention

Every verification decision — approval or rejection — is written to the audit sink
with the deciding service account identity, the clinic identifier, the license status
observed, and the resulting order state. Records are retained for seven years.

# Meridian Clinical Supply — Cold-Chain Handling SOP

> Synthetic sample corpus authored for this demo. The clinical substance reflects
> widely published cold-chain storage practice, but this is *not* a reproduction of
> any real regulatory publication and must not be cited as one.

## Section 1 — Scope

This procedure governs storage, packing, and transport of temperature-sensitive
pharmaceutical products distributed by Meridian Clinical Supply to licensed clinics.
It applies to every SKU flagged `cold_chain_required` in the product catalog.

## Section 2 — Refrigerated Storage Range

Refrigerated biologics, including insulin products such as Insulin Glargine
(SKU-INSULIN-01), must be held between 2°C and 8°C (36°F to 46°F) at all times
during storage and transit. Product must not be frozen. A product that has been
frozen at any point is considered non-viable regardless of subsequent temperature
recovery and must be destroyed rather than returned to stock.

## Section 3 — Temperature Excursion Handling

An excursion is any recorded temperature outside the 2°C–8°C band. Excursions
above 8°C lasting more than 60 continuous minutes require immediate quarantine of
the affected lot. Quarantined lots may not be allocated to new orders until a
qualified pharmacist has reviewed the continuous temperature log and recorded a
disposition decision. Excursions below 0°C require immediate destruction.

## Section 4 — Continuous Monitoring

Every cold-chain shipment carries an IoT temperature logger sampling at no less
than one reading per 15 seconds. Logger data is uploaded on delivery and retained
for seven years. A shipment arriving without a complete logger record is treated
as an excursion of unknown magnitude and quarantined by default.

## Section 5 — Packing Configuration

Cold-chain orders ship in validated insulated containers with phase-change coolant
packs, qualified for a minimum 48-hour hold at ambient temperatures up to 35°C.
Coolant packs must be conditioned to 5°C before packing; frozen packs must never
contact product directly, as this risks freezing the biologic.

## Section 6 — Carrier Requirements

Cold-chain shipments dispatch exclusively via carriers holding an active
refrigerated-transport qualification. Meridian's contracted carrier for
refrigerated biologics is MedExpress ColdChain. Standard ambient freight carriers
must never be assigned to a `cold_chain_required` SKU, and the shipping agent
enforces this at booking time.

## Section 7 — FEFO Allocation

Warehouse allocation follows First-Expiring-First-Out. When multiple lots satisfy
an order quantity, the lot with the nearest expiration date is allocated first.
Lots within 30 days of expiration are flagged for reconciliation review and are
not allocated to new orders without operations approval.

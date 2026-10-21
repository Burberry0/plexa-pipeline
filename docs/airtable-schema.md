# Airtable Schema

Create one base with three tables. Field names must match exactly (the service
writes by name). Single-select options must exist before the first write.

**Every Leads and Messages column below must exist before the matching build is
deployed.** A missing column makes Airtable return 422 and sends every lead to
`Manual Review`. Columns added for the property-matching hand-off (2026-10-13):
Zip Code, Phone, Bathrooms, Adults, Children, Amenities, Special Requests,
Match Ready on Leads; Match Ready on Messages.

`Partners` is CRM / inventory-tier storage. It is not an ingest allowlist
(unknown senders are still processed). Lookup is by Email (exact), with Domain
as fallback. The pipeline does not require Partners columns to exist for
`/ingest` to succeed until partner enrichment is wired.

## Table: Leads (one record per sender email)

The service upserts with `fieldsToMergeOn: ["Email"]`, so Email must stay the primary field and unique.

| Field | Type | Notes |
|---|---|---|
| Email | Single line text | **Primary field.** Lowercased sender address. |
| Name | Single line text | |
| Location | Single line text | |
| Bedrooms | Number (integer) | 0 = studio |
| Budget Min | Currency | |
| Budget Max | Currency | |
| Move-in Date | Single line text | ISO date or "ASAP" |
| Pets | Single line text | "1 dog, 2 cats", "None", or blank |
| Occupants | Number (integer) | |
| Duration Months | Number (integer) | |
| Pet Friendly Required | Checkbox | |
| Zip Code | Single line text | 5 digits; the match-ready gate field |
| Phone | Single line text | As written in the email |
| Bathrooms | Number (1 decimal) | |
| Adults | Number (integer) | |
| Children | Number (integer) | |
| Amenities | Long text | Comma-joined JotForm labels, e.g. "Pool, Yard" |
| Special Requests | Long text | Renter-stated needs (Section 8, ADA, …) |
| Match Ready | Checkbox | True when zip, bedrooms and move-in are all known; written on every upsert |
| Confidence | Number (2 decimals) | |
| Notes | Long text | |
| Tier | Single select | Options: `Tier 1`, `Tier 2`, `Tier 3` |
| Status | Single select | Options: `New`, `Needs Review`, `On Hold`, `Manual Review`, `Matched` |
| Last Subject | Single line text | |
| Last Contact | Date (include time) | ISO 8601 UTC |
| Reply Count | Number (integer) | Incremented by the service when it decides to reply |
| Last Reply At | Date (include time) | ISO 8601 UTC |
| Extraction JSON | Long text | Exact `ExtractedLead` round-trip. Do not edit by hand. |

## Table: Messages (one record per processed message)

| Field | Type | Notes |
|---|---|---|
| Message ID | Single line text | **Primary field.** Gmail message id. Used for idempotency. |
| Email | Single line text | |
| Subject | Single line text | |
| Classification | Single select | Options: `LEAD`, `JUNK` |
| Tier | Single select | Options: `Tier 1`, `Tier 2`, `Tier 3` |
| Status | Single select | Same options as Leads.Status |
| Should Reply | Checkbox | |
| Match Ready | Checkbox | Lead was match-ready after this message |
| Skip Reason | Single line text | |
| Error | Long text | |
| Tokens | Number (integer) | |
| Processed At | Date (include time) | ISO 8601 UTC |

## Table: Partners (one record per known partner contact)

CRM source of truth for partner contacts who inquire about properties or
receive inventory lists. Email must stay the primary field and unique.
Normalize Email and Domain to lowercase on import.

| Field | Type | Notes |
|---|---|---|
| Email | Single line text | **Primary field.** Lowercased partner contact email. Must be unique. Example: `alexandria.negrete@alesolutions.com` |
| First Name | Single line text | May be blank. Example: `Alexandria` |
| Last Name | Single line text | May be blank. Example: `Negrete` |
| Inventory Tier | Single select | Options: `Full`, `Snap`. **Full** = full inventory (e.g. ALE, CRS). **Snap** = snapshot lists to stay engaged (e.g. iZeal Stay–style). Required when known. |
| Vendor | Single select | Options: `ALE`, `Corpay`, `CRS`, `Sedgwick`, `Primus`, `Alacrity`, `TPS`, `Arrow ALE`, `Catale`, `Other`. Use `Other` when the domain does not map to a listed vendor. Corpay is related to ALE but kept separate so rows can sit next to ALE in views. |
| Domain | Single line text | Email domain only, lowercased, no `@`. Example: `alesolutions.com`. Domain-level fallback when exact Email is missing. |
| Company Name | Single line text | Optional free-text company beyond Vendor. Examples: `ALE Solutions`, `Key Luxe Suites` |
| Status | Single select | Options: `Active`, `Inactive`, `Do Not Contact`. Default new imports to `Active`. |
| Notes | Long text | Optional freeform notes (address aliases, import flags, bad emails, etc.). |
| Source | Single select | Options: `Full CSV`, `Snap CSV`, `All Stakeholders`, `Manual` |
| Last Verified | Date | Optional. Date the contact was last confirmed good; leave blank on first import. Format `YYYY-MM-DD`. |

Suggested views: **All Partners** (sort Vendor, Email); **Full Inventory** /
**Snap Inventory** (filter on Inventory Tier); **By Vendor** (group by Vendor).

## Personal access token

Create a token at https://airtable.com/create/tokens with scopes
`data.records:read` and `data.records:write` on this base only. Put it in
`AIRTABLE_API_KEY`. The base id (starts with `app`) goes in `AIRTABLE_BASE_ID`.

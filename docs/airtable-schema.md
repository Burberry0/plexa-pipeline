# Airtable Schema

Create one base with two tables. Field names must match exactly (the service
writes by name). Single-select options must exist before the first write.

**Every column below must exist before the matching build is deployed.** A
missing column makes Airtable return 422 and sends every lead to `Manual
Review`. Columns added for the property-matching hand-off (2026-10-13): Zip
Code, Phone, Bathrooms, Adults, Children, Amenities, Special Requests, Match
Ready on Leads; Match Ready on Messages.

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

## Personal access token

Create a token at https://airtable.com/create/tokens with scopes
`data.records:read` and `data.records:write` on this base only. Put it in
`AIRTABLE_API_KEY`. The base id (starts with `app`) goes in `AIRTABLE_BASE_ID`.

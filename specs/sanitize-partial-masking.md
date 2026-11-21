# Production-linked contact masking

**Status:** implemented locally
**Date:** 2026-11-21
**Scope:** `osh_sanitize` bundled identity and address scripts and restore hooks

## Context

Development copies need recognizable contact and company labels so authorized
developers can compare records with production. Generic `Partner <id>` labels
remove that context. Partial masking is the default, including after restore.

## Contract

- Keep partner IDs and relationships unchanged. Preserve only internal user
  account names and logins, identified by stored `res_users.share = false`.
  External/portal login values are masked like emails with the user row ID.
  If share is not stored, do not assume any user is internal.
- For other partner names and stored name components, keep the first character
  of each alphanumeric run of three or more characters and replace the rest
  with three asterisks. Fully mask one- and two-character runs with three
  asterisks. Keep punctuation and spacing. For example, `Jane Doe` becomes
  `J*** D***`. Nulls and empty values stay unchanged.
- Rebuild stored display names from the masked components, retaining the
  company prefix where supported. Running masking twice keeps the same labels.
- Email: keep one lowercase ASCII local-part initial when the original looks
  like an address with at least three local-part characters. Replace the
  rest and the original domain with a per-record address at `example.invalid`,
  e.g. `j-masked-partner-2@example.invalid`. Keep normalized partner email in
  sync. Mask stored partner, employee, and Flutterwave token contact emails.
  Treat core fallback addresses `dev+<id>@example.local` as having no usable
  production initial.
- Phone: retain only the final four digits from numbers with at least eight
  digits, as `xxxx0100`. Hide all digits of shorter values. Apply to stored
  partner and employee phone fields, including normalized partner phone.
- Address: keep city, state and country for geography. Keep only street
  initials (not house/unit numbers) and, for postcodes of five or more
  characters beginning with two alphanumerics, keep those first two plus
  `***`. Apply to partner and private employee address fields.
- Bank: replace account numbers and their normalized copies with the same
  synthetic, row-specific identifier, keeping up to the final four original
  alphanumerics for accounts with at least eight alphanumerics. Mask holder
  names like contact names and clearing numbers like phones. Turn off outgoing
  payment eligibility where the field exists. Bank IDs and links stay intact.
- Tokens: keep record IDs and links and only a display hint of the trailing
  four digits from `payment_details` or the legacy `name` field. Mask each
  known provider/acquirer credential or customer reference (Mollie customer
  IDs included) entirely with a synthetic token ID. Archive tokens where
  `active` exists. Never keep any part of an actual provider reference. The
  guarded script supports databases without payment and older schemas;
  custom provider fields are out of scope.
- Preserve nulls and empty strings in the newly masked text fields. Make
  these masks stable on a second run. Leave other rules, including government
  identifiers and free text, unchanged. Keep transaction and schema guards.
- Both restore spellings apply the requested sanitization and fingerprint hook.
  With `--anonymize` or `--trim`, a project is required and checked before
  restoring.
  Requested sanitization errors fail the command after restore; the restored
  database is kept. Other post-restore failures retain core warning semantics.
- This is for internal copies only. The legacy `database.is_anonymized` flag
  records completion of the full script set, not an assurance of anonymity.

## Alternatives

- Keep full names: too much production data would be retained.
- Require an opt-in: declined so existing development workflows benefit.
- Keep a suffix of an actual payment credential: display hints and record IDs
  provide enough context without retaining live provider references.

## Tasks

- [x] Update regression expectations and cover repeat runs and short names.
- [x] Implement and document the new default.
- [x] Verify the sanitize suite against PostgreSQL.
- [x] Extend regression coverage to contact, bank and payment tokens.
- [x] Extend regression coverage to address masking.
- [x] Implement and document the extended masking.
- [x] Verify the sanitize suite against PostgreSQL.
- [x] Cover legacy restore spelling and requested-sanitization failure paths.
- [x] Verify portal users, fallback emails and Mollie token masking.

-- Anonymize level 1: identity. Partner names and structured contact,
-- bank and token fields keep limited hints; only internal user account
-- names and logins stay intact, payment provider credentials are
-- replaced, and other fields use the existing deterministic masks. The
-- updates use to_regclass()/column checks so the script serves every
-- Odoo version and module set. The script runs in a single transaction
-- so a failure leaves no partial changes.

BEGIN;

CREATE OR REPLACE FUNCTION pg_temp.osh_columns(target regclass)
RETURNS text[] LANGUAGE sql STABLE STRICT AS $columns$
    SELECT coalesce(array_agg(attname::text), ARRAY[]::text[])
      FROM pg_attribute
     WHERE attrelid = target AND attnum > 0 AND NOT attisdropped;
$columns$;

-- Already masked initials match the first branch so repeated runs are stable.
CREATE OR REPLACE FUNCTION pg_temp.osh_mask_partner_name(value text)
RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $mask$
    SELECT regexp_replace(value,
        '([[:alnum:]])(?:[[:alnum:]]{2,}|[*]{3})|[[:alnum:]]{1,2}',
        $replacement$\1***$replacement$, 'g');
$mask$;

CREATE OR REPLACE FUNCTION pg_temp.osh_mask_email(value text, kind text, row_id bigint)
RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $mask$
    SELECT CASE
        WHEN value = '' OR value ~ ('^([a-z0-9]-)?masked-' || kind || '-' || row_id || '@example[.]invalid$')
            THEN value
        WHEN kind = 'partner' AND (value = 'dev+' || row_id || '@example.local')
            THEN 'masked-partner-' || row_id || '@example.invalid'
        ELSE coalesce(substring(lower(value) from '^([a-z0-9])[a-z0-9._%+-]{2,}@[^@[:space:]]+$') || '-', '')
             || 'masked-' || kind || '-' || row_id || '@example.invalid'
    END;
$mask$;

CREATE OR REPLACE FUNCTION pg_temp.osh_mask_phone(value text)
RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $mask$
    SELECT CASE
        WHEN value = '' OR value ~ '^xxxx[0-9]{4}$' THEN value
        WHEN length(digits) >= 8 THEN 'xxxx' || right(digits, 4)
        ELSE 'xxxx'
    END
    FROM (SELECT regexp_replace(value, '[^0-9]', '', 'g') AS digits) AS phone;
$mask$;

CREATE OR REPLACE FUNCTION pg_temp.osh_mask_bank(value text, row_id bigint)
RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $mask$
    SELECT CASE
        WHEN value = '' OR value ~ ('^MASKED' || row_id || 'X([A-Z0-9]{4})?$') THEN value
        ELSE 'MASKED' || row_id || 'X' || CASE WHEN length(clean) >= 8 THEN right(clean, 4) ELSE '' END
    END
    FROM (SELECT regexp_replace(upper(value), '[^A-Z0-9]', '', 'g') AS clean) AS bank;
$mask$;

CREATE OR REPLACE FUNCTION pg_temp.osh_mask_token_details(value text)
RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $mask$
    SELECT CASE
        WHEN value = '' THEN value
        WHEN rtrim(value) ~ '[0-9]{4}$' THEN '****' || right(rtrim(value), 4)
        ELSE '****'
    END;
$mask$;

DO $$
DECLARE
    col text;
    cols text[] := pg_temp.osh_columns(to_regclass('res_partner'));
    user_cols text[] := pg_temp.osh_columns(to_regclass('res_users'));
    full_name text;
    has_parts boolean;
BEGIN
    IF to_regclass('res_partner') IS NULL THEN
        RETURN;
    END IF;
    IF 'name' = ANY(cols) THEN
        -- Only internal accounts (res_users.share = false) keep the
        -- partner name backing them: it is the user's display name and
        -- developers need to know who they are logging in as. When the
        -- share column is absent no user is assumed internal. Other
        -- partners keep initials.
        IF ARRAY['partner_id', 'share'] <@ user_cols THEN
            UPDATE res_partner AS partner
               SET name = pg_temp.osh_mask_partner_name(partner.name)
             WHERE NOT EXISTS (
                SELECT 1 FROM res_users AS account
                 WHERE account.partner_id = partner.id
                   AND account.share IS FALSE);
        ELSE
            UPDATE res_partner SET name = pg_temp.osh_mask_partner_name(name);
        END IF;
    END IF;
    IF 'email' = ANY(cols) THEN
        UPDATE res_partner SET email = pg_temp.osh_mask_email(email, 'partner', id)
         WHERE email IS NOT NULL;
    END IF;
    IF 'phone' = ANY(cols) THEN
        UPDATE res_partner SET phone = pg_temp.osh_mask_phone(phone) WHERE phone IS NOT NULL;
    END IF;
    IF 'mobile' = ANY(cols) THEN
        UPDATE res_partner SET mobile = pg_temp.osh_mask_phone(mobile) WHERE mobile IS NOT NULL;
    END IF;
    IF 'vat' = ANY(cols) THEN
        UPDATE res_partner SET vat = repeat('x', length(vat)) WHERE vat IS NOT NULL;
    END IF;
    -- OCA partner_firstname and different Odoo versions store name components.
    FOREACH col IN ARRAY ARRAY['firstname', 'lastname', 'company_name',
                               'commercial_company_name'] LOOP
        IF col = ANY(cols) THEN
            EXECUTE format('UPDATE res_partner SET %1$I = pg_temp.osh_mask_partner_name(%1$I)'
                           ' WHERE nullif(%1$I, '''') IS NOT NULL', col);
        END IF;
    END LOOP;
    -- complete_name is stored from Odoo 17, display_name up to 16; both
    -- hold "<company>, <contact>".
    has_parts := ARRAY['name', 'is_company', 'parent_id', 'company_name',
                       'commercial_company_name'] <@ cols;
    IF has_parts THEN
        full_name := $expr$
            CASE
                WHEN NOT coalesce(is_company, false)
                     AND (parent_id IS NOT NULL
                          OR coalesce(company_name, '') <> '')
                THEN coalesce(nullif(commercial_company_name, ''),
                              nullif(company_name, ''),
                              'Partner ' || parent_id,
                              '') || ', ' || name
                ELSE name
            END
        $expr$;
    ELSE
        full_name := 'name';
    END IF;
    FOREACH col IN ARRAY ARRAY['complete_name', 'display_name'] LOOP
        IF 'name' = ANY(cols) AND col = ANY(cols) THEN
            EXECUTE format('UPDATE res_partner SET %I = %s', col, full_name);
        END IF;
    END LOOP;
    IF 'email_normalized' = ANY(cols) THEN
        IF 'email' = ANY(cols) THEN
            UPDATE res_partner
               SET email_normalized = coalesce(nullif(email, ''),
                       pg_temp.osh_mask_email(email_normalized, 'partner', id))
             WHERE nullif(email_normalized, '') IS NOT NULL;
        ELSE
            UPDATE res_partner
               SET email_normalized = pg_temp.osh_mask_email(email_normalized, 'partner', id)
             WHERE email_normalized IS NOT NULL;
        END IF;
    END IF;
    IF 'phone_sanitized' = ANY(cols) THEN
        UPDATE res_partner SET phone_sanitized = pg_temp.osh_mask_phone(phone_sanitized)
         WHERE phone_sanitized IS NOT NULL;
    END IF;
END $$;

-- Only internal accounts keep readable logins; portal logins and logins
-- on accounts without a stored share flag are masked like emails.
-- Passwords are never touched.
DO $$
DECLARE
    cols text[] := pg_temp.osh_columns(to_regclass('res_users'));
BEGIN
    IF 'login' = ANY(cols) THEN
        IF 'share' = ANY(cols) THEN
            UPDATE res_users
               SET login = pg_temp.osh_mask_email(login, 'user', id)
             WHERE share IS DISTINCT FROM false;
        ELSE
            UPDATE res_users
               SET login = pg_temp.osh_mask_email(login, 'user', id);
        END IF;
    END IF;
END $$;

DO $$
DECLARE
    bank_table regclass := to_regclass('res_partner_bank');
    cols text[];
BEGIN
    IF bank_table IS NULL THEN
        RETURN;
    END IF;
    cols := pg_temp.osh_columns(bank_table);
    IF 'acc_number' = ANY(cols) AND 'sanitized_acc_number' = ANY(cols) THEN
        UPDATE res_partner_bank
           SET acc_number = pg_temp.osh_mask_bank(acc_number, id),
               sanitized_acc_number = CASE WHEN nullif(sanitized_acc_number, '') IS NULL
                   THEN sanitized_acc_number
                   ELSE pg_temp.osh_mask_bank(coalesce(nullif(acc_number, ''), sanitized_acc_number), id)
               END;
    ELSIF 'acc_number' = ANY(cols) THEN
        UPDATE res_partner_bank SET acc_number = pg_temp.osh_mask_bank(acc_number, id);
    ELSIF 'sanitized_acc_number' = ANY(cols) THEN
        UPDATE res_partner_bank SET sanitized_acc_number = pg_temp.osh_mask_bank(sanitized_acc_number, id);
    END IF;
    IF 'acc_holder_name' = ANY(cols) THEN
        UPDATE res_partner_bank SET acc_holder_name = pg_temp.osh_mask_partner_name(acc_holder_name)
         WHERE acc_holder_name IS NOT NULL;
    END IF;
    IF 'clearing_number' = ANY(cols) THEN
        UPDATE res_partner_bank SET clearing_number = pg_temp.osh_mask_phone(clearing_number)
         WHERE clearing_number IS NOT NULL;
    END IF;
    IF 'allow_out_payment' = ANY(cols) THEN
        UPDATE res_partner_bank SET allow_out_payment = false WHERE allow_out_payment IS DISTINCT FROM false;
    END IF;
END $$;

-- A display hint is useful; provider credentials must never survive a copy.
DO $$
DECLARE
    cols text[] := pg_temp.osh_columns(to_regclass('payment_token'));
    assignments text[] := ARRAY[]::text[];
    col text;
BEGIN
    FOREACH col IN ARRAY ARRAY['payment_details', 'name'] LOOP
        IF col = ANY(cols) THEN
            assignments := array_append(assignments,
                format('%1$I = pg_temp.osh_mask_token_details(%1$I)', col));
        END IF;
    END LOOP;
    FOREACH col IN ARRAY ARRAY['provider_ref', 'acquirer_ref', 'stripe_payment_method',
                               'stripe_mandate', 'adyen_shopper_reference', 'authorize_profile',
                               'mercado_pago_customer_id', 'mollie_customer_id'] LOOP
        IF col = ANY(cols) THEN
            assignments := array_append(assignments, format(
                '%1$I = CASE WHEN nullif(%1$I, '''') IS NULL THEN %1$I'
                ' ELSE ''osh-disabled-token-'' || id END', col));
        END IF;
    END LOOP;
    IF 'flutterwave_customer_email' = ANY(cols) THEN
        assignments := array_append(assignments,
            'flutterwave_customer_email = pg_temp.osh_mask_email('
            'flutterwave_customer_email, ''token'', id)');
    END IF;
    IF 'active' = ANY(cols) THEN
        assignments := array_append(assignments, 'active = false');
    END IF;
    IF cardinality(assignments) > 0 THEN
        EXECUTE 'UPDATE payment_token SET ' || array_to_string(assignments, ', ');
    END IF;
END $$;

-- Employee identity — guarded: hr may not be installed. The name lives
-- on resource_resource; 10.0 keeps only a stored name_related copy on
-- hr_employee.
DO $$
DECLARE
    cols text[] := pg_temp.osh_columns(to_regclass('hr_employee'));
BEGIN
    IF to_regclass('hr_employee') IS NULL THEN
        RETURN;
    END IF;
    IF 'resource_id' = ANY(cols)
        AND 'name' = ANY(pg_temp.osh_columns(to_regclass('resource_resource'))) THEN
        UPDATE resource_resource r SET name = 'Employee ' || e.id
         FROM hr_employee e WHERE e.resource_id = r.id;
    END IF;
    IF 'name' = ANY(cols) THEN
        UPDATE hr_employee SET name = 'Employee ' || id;
    END IF;
    IF 'name_related' = ANY(cols) THEN
        UPDATE hr_employee SET name_related = 'Employee ' || id;
    END IF;
    IF 'private_email' = ANY(cols) THEN
        UPDATE hr_employee SET private_email = pg_temp.osh_mask_email(private_email, 'employee', id)
         WHERE private_email IS NOT NULL;
    END IF;
    IF 'private_phone' = ANY(cols) THEN
        UPDATE hr_employee SET private_phone = pg_temp.osh_mask_phone(private_phone) WHERE private_phone IS NOT NULL;
    END IF;
    IF 'emergency_contact' = ANY(cols) THEN
        UPDATE hr_employee SET emergency_contact = repeat('x', length(emergency_contact)) WHERE emergency_contact IS NOT NULL;
    END IF;
    IF 'emergency_phone' = ANY(cols) THEN
        UPDATE hr_employee SET emergency_phone = pg_temp.osh_mask_phone(emergency_phone) WHERE emergency_phone IS NOT NULL;
    END IF;
    IF 'identification_id' = ANY(cols) THEN
        UPDATE hr_employee SET identification_id = repeat('x', length(identification_id)) WHERE identification_id IS NOT NULL;
    END IF;
    IF 'passport_id' = ANY(cols) THEN
        UPDATE hr_employee SET passport_id = repeat('x', length(passport_id)) WHERE passport_id IS NOT NULL;
    END IF;
    IF 'ssnid' = ANY(cols) THEN
        UPDATE hr_employee SET ssnid = repeat('x', length(ssnid)) WHERE ssnid IS NOT NULL;
    END IF;
    IF 'sinid' = ANY(cols) THEN
        UPDATE hr_employee SET sinid = repeat('x', length(sinid)) WHERE sinid IS NOT NULL;
    END IF;
    IF 'spouse_complete_name' = ANY(cols) THEN
        UPDATE hr_employee SET spouse_complete_name = repeat('x', length(spouse_complete_name)) WHERE spouse_complete_name IS NOT NULL;
    END IF;
    IF 'permit_no' = ANY(cols) THEN
        UPDATE hr_employee SET permit_no = repeat('x', length(permit_no)) WHERE permit_no IS NOT NULL;
    END IF;
    IF 'visa_no' = ANY(cols) THEN
        UPDATE hr_employee SET visa_no = repeat('x', length(visa_no)) WHERE visa_no IS NOT NULL;
    END IF;
    IF 'work_email' = ANY(cols) THEN
        UPDATE hr_employee SET work_email = pg_temp.osh_mask_email(work_email, 'employee', id)
         WHERE work_email IS NOT NULL;
    END IF;
    IF 'work_phone' = ANY(cols) THEN
        UPDATE hr_employee SET work_phone = pg_temp.osh_mask_phone(work_phone) WHERE work_phone IS NOT NULL;
    END IF;
    IF 'mobile_phone' = ANY(cols) THEN
        UPDATE hr_employee SET mobile_phone = pg_temp.osh_mask_phone(mobile_phone) WHERE mobile_phone IS NOT NULL;
    END IF;
END $$;

-- Chatter that survives the trim retention — bodies, subjects and senders.
DO $$
DECLARE
    cols text[] := pg_temp.osh_columns(to_regclass('mail_message'));
BEGIN
    IF to_regclass('mail_message') IS NULL THEN
        RETURN;
    END IF;
    IF 'body' = ANY(cols) THEN
        UPDATE mail_message SET body = '<p>Message ' || id || '</p>'
         WHERE body IS NOT NULL AND body <> '';
    END IF;
    IF 'subject' = ANY(cols) THEN
        UPDATE mail_message SET subject = 'Message ' || id WHERE subject IS NOT NULL;
    END IF;
    IF 'email_from' = ANY(cols) THEN
        UPDATE mail_message SET email_from = 'message' || id || '@example.local'
         WHERE email_from IS NOT NULL;
    END IF;
    IF 'record_name' = ANY(cols) THEN
        UPDATE mail_message SET record_name = repeat('x', length(record_name))
         WHERE record_name IS NOT NULL;
    END IF;
END $$;

-- Field history that survives the trim retention — tracked old/new values.
DO $$
DECLARE
    cols text[] := pg_temp.osh_columns(to_regclass('mail_tracking_value'));
BEGIN
    IF to_regclass('mail_tracking_value') IS NULL THEN
        RETURN;
    END IF;
    IF 'old_value_char' = ANY(cols) THEN
        UPDATE mail_tracking_value SET old_value_char = repeat('x', length(old_value_char))
         WHERE old_value_char IS NOT NULL;
    END IF;
    IF 'new_value_char' = ANY(cols) THEN
        UPDATE mail_tracking_value SET new_value_char = repeat('x', length(new_value_char))
         WHERE new_value_char IS NOT NULL;
    END IF;
    IF 'old_value_text' = ANY(cols) THEN
        UPDATE mail_tracking_value SET old_value_text = repeat('x', length(old_value_text))
         WHERE old_value_text IS NOT NULL;
    END IF;
    IF 'new_value_text' = ANY(cols) THEN
        UPDATE mail_tracking_value SET new_value_text = repeat('x', length(new_value_text))
         WHERE new_value_text IS NOT NULL;
    END IF;
END $$;

COMMIT;

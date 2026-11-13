-- Anonymize level 1: identity — names, emails, phones, logins and
-- identifier numbers. Deterministic, id-derived values so the result
-- stays coherent across runs and references. Every statement sits in a
-- DO block guarded by to_regclass()/column checks so one script serves
-- every Odoo version and module set. The script runs in a single
-- transaction so a failure leaves no partial changes.

BEGIN;

DO $$
DECLARE
    col text;
    full_name text;
    has_parts boolean;
BEGIN
    IF to_regclass('res_partner') IS NULL THEN
        RETURN;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'res_partner' AND column_name = 'name') THEN
        UPDATE res_partner SET name = 'Partner ' || id;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'res_partner' AND column_name = 'email') THEN
        UPDATE res_partner SET email = 'partner' || id || '@example.local'
         WHERE email IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'res_partner' AND column_name = 'phone') THEN
        UPDATE res_partner SET phone = repeat('x', length(phone)) WHERE phone IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'res_partner' AND column_name = 'mobile') THEN
        UPDATE res_partner SET mobile = repeat('x', length(mobile)) WHERE mobile IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'res_partner' AND column_name = 'vat') THEN
        UPDATE res_partner SET vat = repeat('x', length(vat)) WHERE vat IS NOT NULL;
    END IF;
    -- OCA partner-contact's partner_firstname splits the name.
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'res_partner' AND column_name = 'lastname') THEN
        UPDATE res_partner SET lastname = repeat('x', length(lastname)) WHERE lastname IS NOT NULL;
        UPDATE res_partner SET firstname = repeat('x', length(firstname)) WHERE firstname IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'res_partner' AND column_name = 'company_name') THEN
        UPDATE res_partner SET company_name = 'Company ' || id
         WHERE company_name IS NOT NULL AND company_name <> '';
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'res_partner' AND column_name = 'commercial_company_name') THEN
        IF EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'res_partner' AND column_name = 'commercial_partner_id') THEN
            UPDATE res_partner SET commercial_company_name =
                    'Partner ' || coalesce(commercial_partner_id, id)
             WHERE commercial_company_name IS NOT NULL AND commercial_company_name <> '';
        ELSE
            UPDATE res_partner SET commercial_company_name = 'Partner ' || id
             WHERE commercial_company_name IS NOT NULL AND commercial_company_name <> '';
        END IF;
    END IF;
    -- complete_name is stored from Odoo 17, display_name up to 16; both
    -- hold "<company>, <contact>".
    has_parts := (SELECT count(DISTINCT column_name) = 4 FROM information_schema.columns
                   WHERE table_name = 'res_partner'
                     AND column_name IN ('is_company', 'parent_id',
                                         'company_name', 'commercial_company_name'));
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
        IF EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'res_partner' AND column_name = col) THEN
            EXECUTE format('UPDATE res_partner SET %I = %s', col, full_name);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'res_partner' AND column_name = 'email_normalized') THEN
        UPDATE res_partner SET email_normalized = email
         WHERE email_normalized IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'res_partner' AND column_name = 'phone_sanitized') THEN
        UPDATE res_partner SET phone_sanitized = repeat('x', length(phone_sanitized))
         WHERE phone_sanitized IS NOT NULL;
    END IF;
END $$;

DO $$
DECLARE
    tmp text;
BEGIN
    IF to_regclass('res_users') IS NULL THEN
        RETURN;
    END IF;
    -- login stays unique per record; passwords are left untouched so the
    -- developer is not locked out of the database. The rename goes through
    -- a temporary prefix verified disjoint from all current logins and
    -- unable to collide with the final 'user<id>' values, because the
    -- unique constraint is checked row by row.
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'res_users' AND column_name = 'login') THEN
        LOOP
            tmp := 'osh-tmp-'
                || substr(md5(random()::text || clock_timestamp()::text), 1, 12)
                || '-';
            EXIT WHEN NOT EXISTS (SELECT 1 FROM res_users WHERE login LIKE tmp || '%');
        END LOOP;
        UPDATE res_users SET login = tmp || id;
        UPDATE res_users SET login = 'user' || id;
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('res_partner_bank') IS NULL THEN
        RETURN;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'res_partner_bank' AND column_name = 'acc_number') THEN
        UPDATE res_partner_bank SET acc_number = 'ACC' || id;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'res_partner_bank' AND column_name = 'sanitized_acc_number') THEN
        UPDATE res_partner_bank SET sanitized_acc_number = 'ACC' || id;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'res_partner_bank' AND column_name = 'acc_holder_name') THEN
        UPDATE res_partner_bank SET acc_holder_name = repeat('x', length(acc_holder_name))
         WHERE acc_holder_name IS NOT NULL;
    END IF;
END $$;

-- Employee identity — guarded: hr may not be installed. The name lives
-- on resource_resource; 10.0 keeps only a stored name_related copy on
-- hr_employee.
DO $$
BEGIN
    IF to_regclass('hr_employee') IS NULL THEN
        RETURN;
    END IF;
    IF to_regclass('resource_resource') IS NOT NULL
        AND EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_name = 'hr_employee' AND column_name = 'resource_id') THEN
        UPDATE resource_resource r SET name = 'Employee ' || e.id
         FROM hr_employee e WHERE e.resource_id = r.id;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'hr_employee' AND column_name = 'name') THEN
        UPDATE hr_employee SET name = 'Employee ' || id;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'hr_employee' AND column_name = 'name_related') THEN
        UPDATE hr_employee SET name_related = 'Employee ' || id;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'hr_employee' AND column_name = 'private_email') THEN
        UPDATE hr_employee SET private_email = 'employee' || id || '@example.local';
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'hr_employee' AND column_name = 'private_phone') THEN
        UPDATE hr_employee SET private_phone = repeat('x', length(private_phone)) WHERE private_phone IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'hr_employee' AND column_name = 'emergency_contact') THEN
        UPDATE hr_employee SET emergency_contact = repeat('x', length(emergency_contact)) WHERE emergency_contact IS NOT NULL;
        UPDATE hr_employee SET emergency_phone = repeat('x', length(emergency_phone)) WHERE emergency_phone IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'hr_employee' AND column_name = 'identification_id') THEN
        UPDATE hr_employee SET identification_id = repeat('x', length(identification_id)) WHERE identification_id IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'hr_employee' AND column_name = 'passport_id') THEN
        UPDATE hr_employee SET passport_id = repeat('x', length(passport_id)) WHERE passport_id IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'hr_employee' AND column_name = 'ssnid') THEN
        UPDATE hr_employee SET ssnid = repeat('x', length(ssnid)) WHERE ssnid IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'hr_employee' AND column_name = 'sinid') THEN
        UPDATE hr_employee SET sinid = repeat('x', length(sinid)) WHERE sinid IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'hr_employee' AND column_name = 'spouse_complete_name') THEN
        UPDATE hr_employee SET spouse_complete_name = repeat('x', length(spouse_complete_name)) WHERE spouse_complete_name IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'hr_employee' AND column_name = 'permit_no') THEN
        UPDATE hr_employee SET permit_no = repeat('x', length(permit_no)) WHERE permit_no IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'hr_employee' AND column_name = 'visa_no') THEN
        UPDATE hr_employee SET visa_no = repeat('x', length(visa_no)) WHERE visa_no IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'hr_employee' AND column_name = 'work_email') THEN
        UPDATE hr_employee SET work_email = 'employee' || id || '@example.local'
         WHERE work_email IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'hr_employee' AND column_name = 'work_phone') THEN
        UPDATE hr_employee SET work_phone = repeat('x', length(work_phone)) WHERE work_phone IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'hr_employee' AND column_name = 'mobile_phone') THEN
        UPDATE hr_employee SET mobile_phone = repeat('x', length(mobile_phone)) WHERE mobile_phone IS NOT NULL;
    END IF;
END $$;

-- Field history that survives the trim retention — tracked old/new values.
DO $$
BEGIN
    IF to_regclass('mail_tracking_value') IS NULL THEN
        RETURN;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'mail_tracking_value' AND column_name = 'old_value_char') THEN
        UPDATE mail_tracking_value SET old_value_char = repeat('x', length(old_value_char))
         WHERE old_value_char IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'mail_tracking_value' AND column_name = 'new_value_char') THEN
        UPDATE mail_tracking_value SET new_value_char = repeat('x', length(new_value_char))
         WHERE new_value_char IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'mail_tracking_value' AND column_name = 'old_value_text') THEN
        UPDATE mail_tracking_value SET old_value_text = repeat('x', length(old_value_text))
         WHERE old_value_text IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'mail_tracking_value' AND column_name = 'new_value_text') THEN
        UPDATE mail_tracking_value SET new_value_text = repeat('x', length(new_value_text))
         WHERE new_value_text IS NOT NULL;
    END IF;
END $$;

COMMIT;

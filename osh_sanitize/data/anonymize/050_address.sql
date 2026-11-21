-- Anonymize level 2: keep geography while masking street and postcode details.
DO $$
DECLARE
    target regclass;
    prefix text;
    field text;
    col text;
BEGIN
    FOR target, prefix IN
        SELECT to_regclass(tbl), pfx
          FROM (VALUES ('res_partner', ''), ('hr_employee', 'private_')) AS addresses(tbl, pfx)
    LOOP
        IF target IS NULL THEN
            CONTINUE;
        END IF;
        FOREACH field IN ARRAY ARRAY['street', 'street2', 'zip'] LOOP
            col := prefix || field;
            IF NOT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = target
                            AND attname = col AND attnum > 0 AND NOT attisdropped) THEN
                CONTINUE;
            END IF;
            IF field = 'zip' THEN
                EXECUTE format($sql$
                    UPDATE %1$s SET %2$I = CASE
                        WHEN length(%2$I) >= 5 AND %2$I ~ '^[[:alnum:]]{2}'
                            THEN left(%2$I, 2) || '***'
                        ELSE '***'
                    END WHERE nullif(%2$I, '') IS NOT NULL
                $sql$, target, col);
            ELSE
                EXECUTE format($sql$
                    UPDATE %1$s SET %2$I = regexp_replace(%2$I,
                        '([[:alpha:]])(?:[[:alnum:]]{2,}|[*]{3})|[[:alnum:]]+',
                        $replacement$\1***$replacement$, 'g')
                    WHERE nullif(%2$I, '') IS NOT NULL
                $sql$, target, col);
            END IF;
        END LOOP;
    END LOOP;
END $$;

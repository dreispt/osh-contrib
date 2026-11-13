-- Mark the database as anonymized. Runs only with the full anonymize set:
-- 'osh db sanitize' drops it when levels or scripts are left out.
DO $$
BEGIN
    IF to_regclass('ir_config_parameter') IS NULL THEN
        RETURN;
    END IF;
    INSERT INTO ir_config_parameter (key, value)
    VALUES ('database.is_anonymized', 'true')
        ON CONFLICT (key) DO
           UPDATE SET value = 'true';
END $$;

-- Trim: SMS queue.
DO $$
BEGIN
    IF to_regclass('sms_sms') IS NOT NULL THEN
        DELETE FROM sms_sms;
    END IF;
END $$;

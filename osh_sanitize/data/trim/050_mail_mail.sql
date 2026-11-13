-- Trim: outgoing mail queue.
DO $$
BEGIN
    IF to_regclass('mail_mail') IS NOT NULL THEN
        DELETE FROM mail_mail;
    END IF;
END $$;

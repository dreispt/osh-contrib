-- Trim: processed queue_job records — pending and failed jobs stay.
DO $$
BEGIN
    IF to_regclass('queue_job') IS NOT NULL THEN
        DELETE FROM queue_job WHERE state IN ('done', 'cancelled');
    END IF;
END $$;

-- Backfill saved payers without regenerating their IDs or reference data.
-- New databases create this column through BaseGenerator's table definition.
DO $$
BEGIN
    IF to_regclass('payers') IS NOT NULL THEN
        ALTER TABLE payers ADD COLUMN IF NOT EXISTS is_skilled BOOLEAN;
        UPDATE payers
        SET is_skilled = payer_type IN ('medicare', 'medicare_hmo', 'medicare_comm', 'va')
        WHERE is_skilled IS DISTINCT FROM
            (payer_type IN ('medicare', 'medicare_hmo', 'medicare_comm', 'va'));
        ALTER TABLE payers ALTER COLUMN is_skilled SET NOT NULL;
    END IF;
END;
$$;

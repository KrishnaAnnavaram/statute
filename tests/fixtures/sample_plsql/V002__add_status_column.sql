-- Flyway-style migration: no CREATE object, so it falls back to MIGRATION
-- classification by filename convention.
ALTER TABLE app.accounts ADD status VARCHAR2(10) DEFAULT 'ACTIVE';

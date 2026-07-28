/*==============================================================================
  Fixture: advanced_schema.sql
  Purpose : Exercises every DDL construct the Data Agent (03_data.py) extracts,
            especially the ones that are easy to silently drop. Each block is
            referenced by an assertion in tests/test_data.py.

  Deliberately includes constraints in all three Oracle enforcement states
  (ENABLE VALIDATE / ENABLE NOVALIDATE / DISABLE) because a DISABLED
  constraint must never be reported downstream as an active business rule.
==============================================================================*/

-----------------------------------------------------------------------------
-- SEQUENCES — full metadata (max/min/cycle/cache), not just start/increment
-----------------------------------------------------------------------------
CREATE SEQUENCE seq_order_id
    START WITH 5000 INCREMENT BY 10
    MAXVALUE 9999999 MINVALUE 1000
    CYCLE CACHE 50;

CREATE SEQUENCE seq_plain_id;

-----------------------------------------------------------------------------
-- PARTIES — IDENTITY column, virtual column, inline + out-of-line constraints
-----------------------------------------------------------------------------
CREATE TABLE parties (
    party_id        NUMBER GENERATED ALWAYS AS IDENTITY (START WITH 1 INCREMENT BY 1),
    first_name      VARCHAR2(60)  NOT NULL,
    last_name       VARCHAR2(60)  NOT NULL,
    display_name    VARCHAR2(130) GENERATED ALWAYS AS (first_name || ' ' || last_name) VIRTUAL,
    party_type      VARCHAR2(20)  NOT NULL,   -- INDIVIDUAL, CORPORATE, TRUST
    email           VARCHAR2(120),
    created_on      DATE DEFAULT SYSDATE NOT NULL,
    CONSTRAINT pk_parties PRIMARY KEY (party_id),
    CONSTRAINT uq_parties_email UNIQUE (email),
    CONSTRAINT ck_parties_type CHECK (party_type IN ('INDIVIDUAL','CORPORATE','TRUST'))
);

COMMENT ON TABLE parties IS 'Legal entities that can hold a contract';
COMMENT ON COLUMN parties.party_type IS 'Legal classification driving KYC requirements';

-----------------------------------------------------------------------------
-- CONTRACTS — partitioned, FK with ON DELETE CASCADE, a DISABLED check
-----------------------------------------------------------------------------
CREATE TABLE contracts (
    contract_id     NUMBER        NOT NULL,
    party_id        NUMBER        NOT NULL,
    contract_status VARCHAR2(20)  DEFAULT 'DRAFT' NOT NULL,
    premium_amount  NUMBER(18,2)  NOT NULL,
    start_date      DATE          NOT NULL,
    CONSTRAINT pk_contracts PRIMARY KEY (contract_id),
    CONSTRAINT fk_contracts_party FOREIGN KEY (party_id)
        REFERENCES parties (party_id) ON DELETE CASCADE,
    -- Left DISABLED after a historical data migration; the database is NOT
    -- enforcing this. It must never appear as a confirmed business rule.
    CONSTRAINT ck_contracts_premium CHECK (premium_amount > 0) DISABLE,
    -- Enforced going forward, but legacy rows were never checked.
    CONSTRAINT ck_contracts_status CHECK (contract_status IN ('DRAFT','ACTIVE','LAPSED'))
        ENABLE NOVALIDATE
)
PARTITION BY RANGE (start_date) (
    PARTITION p_2024 VALUES LESS THAN (TO_DATE('2025-01-01','YYYY-MM-DD')),
    PARTITION p_2025 VALUES LESS THAN (TO_DATE('2026-01-01','YYYY-MM-DD')),
    PARTITION p_max  VALUES LESS THAN (MAXVALUE)
);

-----------------------------------------------------------------------------
-- CLAIMS — FK with ON DELETE SET NULL, implicit (undeclared) FK to parties
-----------------------------------------------------------------------------
CREATE TABLE claims (
    claim_id        NUMBER        NOT NULL,
    contract_id     NUMBER,
    -- No FOREIGN KEY declared, but the name+type match parties.party_id.
    -- Must be reported as an INFERRED relationship, never as a declared one.
    party_id        NUMBER,
    claim_amount    NUMBER(18,2)  NOT NULL,
    claim_status    VARCHAR2(20)  DEFAULT 'OPEN',
    CONSTRAINT pk_claims PRIMARY KEY (claim_id),
    CONSTRAINT fk_claims_contract FOREIGN KEY (contract_id)
        REFERENCES contracts (contract_id) ON DELETE SET NULL
);

-----------------------------------------------------------------------------
-- GLOBAL TEMPORARY TABLE — ephemeral, must not be treated as persistent
-----------------------------------------------------------------------------
CREATE GLOBAL TEMPORARY TABLE tmp_claim_batch (
    claim_id    NUMBER,
    scratch_val NUMBER(18,2)
) ON COMMIT DELETE ROWS;

-----------------------------------------------------------------------------
-- VIEW — the WHERE clause IS the business rule, not a convenience alias
-----------------------------------------------------------------------------
CREATE OR REPLACE VIEW active_contracts AS
    SELECT contract_id, party_id, premium_amount
    FROM contracts
    WHERE contract_status = 'ACTIVE' AND premium_amount > 0;

-----------------------------------------------------------------------------
-- INDEXES — a UNIQUE index is a de facto business rule even with no
-- corresponding UNIQUE constraint
-----------------------------------------------------------------------------
CREATE UNIQUE INDEX uix_claims_contract_amt ON claims (contract_id, claim_amount);
CREATE INDEX ix_contracts_status ON contracts (contract_status);

-----------------------------------------------------------------------------
-- SYNONYM — cross-schema alias that must resolve during cross-validation
-----------------------------------------------------------------------------
CREATE OR REPLACE PUBLIC SYNONYM syn_parties FOR app.parties;

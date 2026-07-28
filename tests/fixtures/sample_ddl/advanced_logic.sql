/*==============================================================================
  Fixture: advanced_logic.sql
  Purpose : Companion to advanced_schema.sql. Exercises the Data Agent's
            "close the loop back to Agent 2" paths — %TYPE / %ROWTYPE
            resolution, synonym resolution during cross-validation, column
            usage tracking, and sequence usage linkage.
==============================================================================*/

CREATE OR REPLACE PROCEDURE sp_register_claim (
    p_claim_id      IN  NUMBER,
    p_contract_id   IN  NUMBER,
    p_amount        IN  NUMBER,
    p_result        OUT VARCHAR2
)
IS
    -- %TYPE against a real column — must resolve to contracts.contract_status
    v_contract_status  contracts.contract_status%TYPE;
    -- %TYPE against a column that does NOT exist — must be reported unresolved
    v_bogus            contracts.no_such_column%TYPE;
    v_premium          NUMBER(18,2);
BEGIN
    SELECT contract_status, premium_amount
      INTO v_contract_status, v_premium
      FROM contracts
     WHERE contract_id = p_contract_id;

    IF v_contract_status <> 'ACTIVE' THEN
        p_result := 'CONTRACT_NOT_ACTIVE';
        RETURN;
    END IF;

    INSERT INTO claims (claim_id, contract_id, claim_amount, claim_status)
    VALUES (seq_order_id.NEXTVAL, p_contract_id, p_amount, 'OPEN');

    COMMIT;
    p_result := 'CLAIM_REGISTERED';

EXCEPTION
    WHEN NO_DATA_FOUND THEN
        p_result := 'CONTRACT_NOT_FOUND';
    WHEN OTHERS THEN
        ROLLBACK;
        RAISE;
END sp_register_claim;
/

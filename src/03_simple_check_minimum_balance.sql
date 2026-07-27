/*==============================================================================
  Program   : 03_simple_check_minimum_balance.sql
  Category  : SIMPLE
  Purpose   : Check whether an account's current balance is below the
              minimum balance requirement for its account type, and
              compute the penalty charge if applicable.
  Pattern   : Single procedure, CASE expression, single-row lookups.
==============================================================================*/

CREATE OR REPLACE PROCEDURE sp_check_minimum_balance (
    p_account_number   IN  VARCHAR2,
    p_penalty_amount   OUT NUMBER,
    p_shortfall_amount OUT NUMBER,
    p_message          OUT VARCHAR2
)
IS
    v_current_balance   NUMBER(18,2);
    v_account_type      VARCHAR2(20);
    v_min_balance_req   NUMBER(18,2);
BEGIN
    SELECT balance, account_type
      INTO v_current_balance, v_account_type
      FROM accounts
     WHERE account_number = p_account_number;

    -- Determine minimum balance requirement based on account type
    v_min_balance_req :=
        CASE v_account_type
            WHEN 'SAVINGS_REGULAR'  THEN 1000
            WHEN 'SAVINGS_PREMIUM'  THEN 10000
            WHEN 'SAVINGS_ZERO_BAL' THEN 0
            WHEN 'CURRENT_REGULAR'  THEN 5000
            WHEN 'CURRENT_PREMIUM'  THEN 25000
            ELSE 1000
        END;

    IF v_current_balance >= v_min_balance_req THEN
        p_shortfall_amount := 0;
        p_penalty_amount   := 0;
        p_message := 'BALANCE_OK';
    ELSE
        p_shortfall_amount := v_min_balance_req - v_current_balance;

        -- Penalty is 5% of shortfall, capped at 500, floored at 50
        p_penalty_amount := LEAST(500, GREATEST(50, ROUND(p_shortfall_amount * 0.05, 2)));
        p_message := 'BELOW_MINIMUM_BALANCE';
    END IF;

EXCEPTION
    WHEN NO_DATA_FOUND THEN
        p_message := 'ACCOUNT_NOT_FOUND';
        p_penalty_amount := NULL;
        p_shortfall_amount := NULL;
    WHEN OTHERS THEN
        p_message := 'ERROR: ' || SQLERRM;
        RAISE;
END sp_check_minimum_balance;
/

-- Sample usage:
-- DECLARE
--     v_penalty   NUMBER;
--     v_shortfall NUMBER;
--     v_msg       VARCHAR2(100);
-- BEGIN
--     sp_check_minimum_balance('AC1000234567', v_penalty, v_shortfall, v_msg);
--     DBMS_OUTPUT.PUT_LINE(v_msg || ' Penalty=' || v_penalty || ' Shortfall=' || v_shortfall);
-- END;
-- /
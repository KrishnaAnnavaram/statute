/*==============================================================================
  Program   : 02_simple_update_dormant_account_status.sql
  Category  : SIMPLE
  Purpose   : Update a single account's status to DORMANT if there has been
              no customer-initiated transaction for more than 365 days.
  Pattern   : Single procedure, one UPDATE, IF/ELSE, exception handling.
==============================================================================*/

CREATE OR REPLACE PROCEDURE sp_update_dormant_account_status (
    p_account_number  IN VARCHAR2,
    p_as_of_date      IN DATE DEFAULT SYSDATE,
    p_result          OUT VARCHAR2
)
IS
    v_last_txn_date     DATE;
    v_current_status    VARCHAR2(20);
    v_days_inactive     NUMBER;
BEGIN
    -- Fetch last transaction date and current status
    SELECT last_transaction_date, account_status
      INTO v_last_txn_date, v_current_status
      FROM accounts
     WHERE account_number = p_account_number;

    v_days_inactive := p_as_of_date - NVL(v_last_txn_date, p_as_of_date - 9999);

    IF v_days_inactive > 365 AND v_current_status = 'ACTIVE' THEN

        UPDATE accounts
           SET account_status = 'DORMANT',
               status_change_date = p_as_of_date,
               last_modified_by   = 'SYSTEM_BATCH'
         WHERE account_number = p_account_number;

        p_result := 'ACCOUNT_MARKED_DORMANT';

    ELSIF v_days_inactive <= 365 AND v_current_status = 'DORMANT' THEN

        -- Reactivate if a transaction has occurred recently
        UPDATE accounts
           SET account_status = 'ACTIVE',
               status_change_date = p_as_of_date,
               last_modified_by   = 'SYSTEM_BATCH'
         WHERE account_number = p_account_number;

        p_result := 'ACCOUNT_REACTIVATED';

    ELSE
        p_result := 'NO_STATUS_CHANGE_REQUIRED';
    END IF;

    COMMIT;

EXCEPTION
    WHEN NO_DATA_FOUND THEN
        p_result := 'ACCOUNT_NOT_FOUND';
    WHEN OTHERS THEN
        ROLLBACK;
        p_result := 'ERROR: ' || SQLERRM;
        RAISE;
END sp_update_dormant_account_status;
/

-- Sample usage:
-- DECLARE
--     v_result VARCHAR2(100);
-- BEGIN
--     sp_update_dormant_account_status('AC1000234567', SYSDATE, v_result);
--     DBMS_OUTPUT.PUT_LINE(v_result);
-- END;
-- /
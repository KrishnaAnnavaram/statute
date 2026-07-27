/*==============================================================================
  Program   : 04_medium_process_monthly_interest_credit.sql
  Category  : MEDIUM
  Purpose   : Monthly batch job that calculates and credits interest for all
              active savings accounts, using tiered interest rates based on
              balance slabs, and logs every credit transaction.
  Pattern   : Explicit cursor loop, tiered rate logic, INSERT ledger entries,
              per-row exception handling that does not stop the batch.
==============================================================================*/

CREATE OR REPLACE PROCEDURE sp_process_monthly_interest_credit (
    p_run_date       IN DATE DEFAULT SYSDATE,
    p_accounts_processed OUT NUMBER,
    p_accounts_failed    OUT NUMBER
)
IS
    CURSOR c_savings_accounts IS
        SELECT account_number, customer_id, balance, account_type
          FROM accounts
         WHERE account_status = 'ACTIVE'
           AND account_type LIKE 'SAVINGS%';

    v_interest_rate    NUMBER(5,3);
    v_days_in_month    NUMBER;
    v_interest_amount  NUMBER(18,2);
    v_new_balance      NUMBER(18,2);

BEGIN
    p_accounts_processed := 0;
    p_accounts_failed    := 0;

    v_days_in_month := EXTRACT(DAY FROM LAST_DAY(p_run_date));

    FOR rec IN c_savings_accounts LOOP

        BEGIN
            -- Tiered interest rate based on balance slab (illustrative rates)
            IF rec.balance < 100000 THEN
                v_interest_rate := 3.0;
            ELSIF rec.balance < 1000000 THEN
                v_interest_rate := 3.5;
            ELSIF rec.balance < 10000000 THEN
                v_interest_rate := 4.0;
            ELSE
                v_interest_rate := 4.5;
            END IF;

            -- Prorated monthly interest, compounded monthly, annual rate basis
            v_interest_amount := ROUND(
                rec.balance * (v_interest_rate / 100) * (v_days_in_month / 365),
                2
            );

            IF v_interest_amount > 0 THEN

                v_new_balance := rec.balance + v_interest_amount;

                UPDATE accounts
                   SET balance = v_new_balance,
                       last_transaction_date = p_run_date
                 WHERE account_number = rec.account_number;

                INSERT INTO transaction_ledger (
                    txn_id, account_number, txn_date, txn_type,
                    txn_amount, running_balance, narration
                ) VALUES (
                    seq_txn_id.NEXTVAL, rec.account_number, p_run_date, 'INT_CREDIT',
                    v_interest_amount, v_new_balance,
                    'Monthly interest credit @ ' || v_interest_rate || '%'
                );

                p_accounts_processed := p_accounts_processed + 1;
            END IF;

        EXCEPTION
            WHEN OTHERS THEN
                -- Log failure for this account but keep processing the rest
                INSERT INTO batch_error_log (
                    log_id, batch_name, entity_key, error_message, log_date
                ) VALUES (
                    seq_log_id.NEXTVAL, 'MONTHLY_INTEREST_CREDIT',
                    rec.account_number, SQLERRM, p_run_date
                );
                p_accounts_failed := p_accounts_failed + 1;
        END;

    END LOOP;

    COMMIT;

EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        RAISE_APPLICATION_ERROR(-20010,
            'sp_process_monthly_interest_credit failed: ' || SQLERRM);
END sp_process_monthly_interest_credit;
/

-- Sample usage:
-- DECLARE
--     v_processed NUMBER;
--     v_failed    NUMBER;
-- BEGIN
--     sp_process_monthly_interest_credit(SYSDATE, v_processed, v_failed);
--     DBMS_OUTPUT.PUT_LINE('Processed=' || v_processed || ' Failed=' || v_failed);
-- END;
-- /
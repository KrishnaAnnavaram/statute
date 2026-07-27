/*==============================================================================
  Program   : 05_medium_fund_transfer_with_validation.sql
  Category  : MEDIUM
  Purpose   : Transfer funds between two accounts with full validation:
              account existence, status, balance sufficiency, daily
              transfer limit check, and atomic debit/credit with logging.
  Pattern   : Multiple validations, custom exceptions, two-phase
              debit/credit with SAVEPOINT rollback on failure.
==============================================================================*/

CREATE OR REPLACE PROCEDURE sp_transfer_funds (
    p_from_account   IN  VARCHAR2,
    p_to_account     IN  VARCHAR2,
    p_amount         IN  NUMBER,
    p_txn_ref        IN  VARCHAR2,
    p_status         OUT VARCHAR2,
    p_message        OUT VARCHAR2
)
IS
    v_from_balance      NUMBER(18,2);
    v_from_status       VARCHAR2(20);
    v_to_status         VARCHAR2(20);
    v_daily_limit       NUMBER(18,2);
    v_today_txn_total   NUMBER(18,2);

    e_account_not_found     EXCEPTION;
    e_account_inactive      EXCEPTION;
    e_insufficient_balance  EXCEPTION;
    e_daily_limit_exceeded  EXCEPTION;
    e_invalid_amount        EXCEPTION;

BEGIN
    p_status := 'FAILED';

    IF p_amount IS NULL OR p_amount <= 0 THEN
        RAISE e_invalid_amount;
    END IF;

    IF p_from_account = p_to_account THEN
        p_status  := 'FAILED';
        p_message := 'Source and destination accounts cannot be the same.';
        RETURN;
    END IF;

    SAVEPOINT sp_before_transfer;

    -- Validate source account
    BEGIN
        SELECT balance, account_status, daily_transfer_limit
          INTO v_from_balance, v_from_status, v_daily_limit
          FROM accounts
         WHERE account_number = p_from_account
           FOR UPDATE;
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            RAISE e_account_not_found;
    END;

    IF v_from_status <> 'ACTIVE' THEN
        RAISE e_account_inactive;
    END IF;

    -- Validate destination account
    BEGIN
        SELECT account_status INTO v_to_status
          FROM accounts
         WHERE account_number = p_to_account
           FOR UPDATE;
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            RAISE e_account_not_found;
    END;

    IF v_to_status <> 'ACTIVE' THEN
        RAISE e_account_inactive;
    END IF;

    IF v_from_balance < p_amount THEN
        RAISE e_insufficient_balance;
    END IF;

    -- Check today's cumulative outward transfers against the daily limit
    SELECT NVL(SUM(txn_amount), 0)
      INTO v_today_txn_total
      FROM transaction_ledger
     WHERE account_number = p_from_account
       AND txn_type = 'TRANSFER_OUT'
       AND TRUNC(txn_date) = TRUNC(SYSDATE);

    IF (v_today_txn_total + p_amount) > v_daily_limit THEN
        RAISE e_daily_limit_exceeded;
    END IF;

    -- Debit source
    UPDATE accounts
       SET balance = balance - p_amount,
           last_transaction_date = SYSDATE
     WHERE account_number = p_from_account;

    INSERT INTO transaction_ledger (
        txn_id, account_number, txn_date, txn_type, txn_amount,
        running_balance, reference_number, narration
    ) VALUES (
        seq_txn_id.NEXTVAL, p_from_account, SYSDATE, 'TRANSFER_OUT', p_amount,
        v_from_balance - p_amount, p_txn_ref, 'Transfer to ' || p_to_account
    );

    -- Credit destination
    UPDATE accounts
       SET balance = balance + p_amount,
           last_transaction_date = SYSDATE
     WHERE account_number = p_to_account;

    INSERT INTO transaction_ledger (
        txn_id, account_number, txn_date, txn_type, txn_amount,
        running_balance, reference_number, narration
    ) VALUES (
        seq_txn_id.NEXTVAL, p_to_account, SYSDATE, 'TRANSFER_IN', p_amount,
        (SELECT balance FROM accounts WHERE account_number = p_to_account),
        p_txn_ref, 'Transfer from ' || p_from_account
    );

    p_status  := 'SUCCESS';
    p_message := 'Transfer completed successfully.';
    COMMIT;

EXCEPTION
    WHEN e_invalid_amount THEN
        p_status := 'FAILED'; p_message := 'Transfer amount must be greater than zero.';
    WHEN e_account_not_found THEN
        ROLLBACK TO sp_before_transfer;
        p_status := 'FAILED'; p_message := 'One or both accounts do not exist.';
    WHEN e_account_inactive THEN
        ROLLBACK TO sp_before_transfer;
        p_status := 'FAILED'; p_message := 'One or both accounts are not active.';
    WHEN e_insufficient_balance THEN
        ROLLBACK TO sp_before_transfer;
        p_status := 'FAILED'; p_message := 'Insufficient balance in source account.';
    WHEN e_daily_limit_exceeded THEN
        ROLLBACK TO sp_before_transfer;
        p_status := 'FAILED'; p_message := 'Daily transfer limit exceeded.';
    WHEN OTHERS THEN
        ROLLBACK TO sp_before_transfer;
        p_status := 'FAILED'; p_message := 'Unexpected error: ' || SQLERRM;
        RAISE;
END sp_transfer_funds;
/
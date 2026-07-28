/*==============================================================================
  Fixture: txn_hazards.sql
  Purpose : Exercises the transaction-boundary analysis, which exists because
            Apache Spark has no transactions — every boundary here is a
            decision someone must make during a migration.

  Contains, deliberately:
    1. sp_incremental_commit  - COMMIT inside a cursor loop. This is the
       documented Oracle "incremental commit" / "fetch across commit"
       anti-pattern: committing inside the loop frees undo that the still-open
       cursor needs, making ORA-01555 "snapshot too old" MORE likely, not
       less. It also destroys atomicity.
    2. sp_savepoint_user      - SAVEPOINT / partial rollback, which has no
       Spark equivalent at all.
    3. sp_no_txn_control      - no COMMIT or ROLLBACK: the transaction
       boundary belongs to the caller.
==============================================================================*/

-----------------------------------------------------------------------------
-- 1. COMMIT inside a loop  (expected: COMMIT_INSIDE_LOOP, high severity)
-----------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE sp_incremental_commit
IS
    CURSOR c_accounts IS
        SELECT account_number, balance FROM accounts;
BEGIN
    FOR rec IN c_accounts LOOP
        UPDATE accounts
           SET balance = balance + 1
         WHERE account_number = rec.account_number;
        COMMIT;                       -- the anti-pattern
    END LOOP;
END sp_incremental_commit;
/

-----------------------------------------------------------------------------
-- 2. SAVEPOINT usage  (expected: SAVEPOINT_PARTIAL_ROLLBACK, high severity)
-----------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE sp_savepoint_user (
    p_account  IN VARCHAR2
)
IS
BEGIN
    SAVEPOINT before_update;

    UPDATE accounts
       SET account_status = 'DORMANT'
     WHERE account_number = p_account;

    COMMIT;
EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK TO before_update;
        RAISE;
END sp_savepoint_user;
/

-----------------------------------------------------------------------------
-- 3. No transaction control  (expected: NO_TRANSACTION_CONTROL, info)
-----------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE sp_no_txn_control (
    p_account  IN  VARCHAR2,
    p_balance  OUT NUMBER
)
IS
BEGIN
    SELECT balance
      INTO p_balance
      FROM accounts
     WHERE account_number = p_account;
END sp_no_txn_control;
/

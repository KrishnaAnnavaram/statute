CREATE OR REPLACE PACKAGE app.account_mgmt IS
    PROCEDURE credit_account(p_id NUMBER, p_amt NUMBER);
    PROCEDURE debit_account(p_id NUMBER, p_amt NUMBER);
    FUNCTION get_balance(p_id NUMBER) RETURN NUMBER;
END account_mgmt;
/

CREATE OR REPLACE PACKAGE BODY app.account_mgmt IS

    PROCEDURE credit_account(p_id NUMBER, p_amt NUMBER) IS
        l_balance app.accounts.balance%TYPE;
    BEGIN
        UPDATE app.accounts SET balance = balance + p_amt WHERE account_id = p_id;
        DBMS_OUTPUT.PUT_LINE('Credited account ' || p_id);
        audit_log_pkg.record_txn(p_id, p_amt);
    END credit_account;

    PROCEDURE debit_account(p_id NUMBER, p_amt NUMBER) IS
    BEGIN
        credit_account(p_id, -p_amt);
    END debit_account;

    FUNCTION get_balance(p_id NUMBER) RETURN NUMBER IS
        l_sql VARCHAR2(200);
        l_bal NUMBER;
    BEGIN
        l_sql := 'SELECT balance FROM app.accounts WHERE account_id = :1';
        EXECUTE IMMEDIATE l_sql INTO l_bal USING p_id;
        RETURN l_bal;
    END get_balance;

END account_mgmt;
/

CREATE OR REPLACE TRIGGER app.accounts_biu
BEFORE INSERT OR UPDATE ON app.accounts
FOR EACH ROW
BEGIN
    :new.balance := NVL(:new.balance, 0);
END;
/

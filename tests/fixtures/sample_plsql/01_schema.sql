-- Schema objects: table, sequence, index, view, synonym, grant
CREATE TABLE app.accounts (
    account_id   NUMBER PRIMARY KEY,
    owner_name   VARCHAR2(100),
    balance      NUMBER(15,2)
);

CREATE SEQUENCE app.account_id_seq START WITH 1000;

CREATE UNIQUE INDEX app.accounts_owner_idx ON app.accounts (owner_name);

CREATE OR REPLACE VIEW app.active_accounts AS
    SELECT account_id, owner_name, balance
    FROM app.accounts
    WHERE balance > 0;

CREATE OR REPLACE PUBLIC SYNONYM accounts_syn FOR app.accounts;

GRANT SELECT ON app.accounts TO reporting_role;

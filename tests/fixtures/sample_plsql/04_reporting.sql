CREATE OR REPLACE VIEW app.remote_positions AS
    SELECT account_id, balance
    FROM app.accounts@finance_link
    WHERE balance > 0;

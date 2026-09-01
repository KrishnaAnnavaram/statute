---
type: Index
title: Business Rules Index
description: Every gating condition in the schema and programs as a traceable BR-NN rule - plain-English obligation, verbatim expression, file:line citation, enforcing object, DATABASE-vs-CODE type, and category.
tags: [business-rules, traceability, index, validation, calculation]
---

# Business Rules Index

Every condition that gates an outcome is a numbered rule with a stable `BR-NN` ID. Traceability is mandatory: each rule cites its source file and line(s), names the enforcing program or constraint, and states whether it is enforced by the **DATABASE** (a schema constraint) or by **CODE** (procedural logic) — these fail differently. Categories are Validation, Calculation, Routing, Limit-check, or Error-handling. IDs are assigned once and never renumbered.

## Index

| ID | Rule | Source file:line | Enforced by | Type | Category |
| --- | --- | --- | --- | --- | --- |
| BR-01 | Account status must be one of ACTIVE, DORMANT, CLOSED | `00_ddl_create_schema.sql:69` | `ck_accounts_status` | DATABASE | Validation |
| BR-02 | Principal must be greater than zero | `01_simple_calculate_simple_interest.sql:19-21` | `fn_calculate_simple_interest` | CODE | Validation |
| BR-03 | Interest rate must not be negative | `01_simple_calculate_simple_interest.sql:23-25` | `fn_calculate_simple_interest` | CODE | Validation |
| BR-04 | Tenure in days must be greater than zero | `01_simple_calculate_simple_interest.sql:27-29` | `fn_calculate_simple_interest` | CODE | Validation |
| BR-05 | Day-count basis is 360 only when '360' is passed, otherwise 365 | `01_simple_calculate_simple_interest.sql:32-36` | `fn_calculate_simple_interest` | CODE | Routing |
| BR-06 | Simple interest = P * R * T / (100 * basis), rounded to 2 decimals | `01_simple_calculate_simple_interest.sql:39-40` | `fn_calculate_simple_interest` | CODE | Calculation |
| BR-07 | Mark an active account DORMANT after more than 365 inactive days | `02_simple_update_dormant_account_status.sql:27` | `sp_update_dormant_account_status` | CODE | Limit-check |
| BR-08 | Treat a NULL last transaction date as ~9999 days inactive | `02_simple_update_dormant_account_status.sql:25` | `sp_update_dormant_account_status` | CODE | Routing |
| BR-09 | Reactivate a DORMANT account when inactivity falls to 365 days or fewer | `02_simple_update_dormant_account_status.sql:37` | `sp_update_dormant_account_status` | CODE | Routing |
| BR-10 | Below-minimum penalty is 5% of shortfall, floored at 50 and capped at 500 | `03_simple_check_minimum_balance.sql:45` | `sp_check_minimum_balance` | CODE | Calculation |
| BR-11 | A per-account failure is logged and the batch continues | `04_medium_process_monthly_interest_credit.sql:75-85` | `sp_process_monthly_interest_credit` | CODE | Error-handling |
| BR-12 | Monthly-credit rate is tiered by balance: 3.0/3.5/4.0/4.5% | `04_medium_process_monthly_interest_credit.sql:38-46` | `sp_process_monthly_interest_credit` | CODE | Routing |
| BR-13 | Monthly interest = balance * rate/100 * days_in_month/365, rounded to 2 | `04_medium_process_monthly_interest_credit.sql:49-52` | `sp_process_monthly_interest_credit` | CODE | Calculation |
| BR-14 | Only ACTIVE accounts whose type starts SAVINGS are credited | `04_medium_process_monthly_interest_credit.sql:19-21` | `sp_process_monthly_interest_credit` | CODE | Routing |
| BR-15 | Interest is credited only when the computed amount is positive | `04_medium_process_monthly_interest_credit.sql:54` | `sp_process_monthly_interest_credit` | CODE | Routing |
| BR-16 | Transfer amount must be greater than zero | `05_medium_fund_transfer_with_validation.sql:35-37` | `sp_transfer_funds` | CODE | Validation |
| BR-17 | Source and destination accounts must differ | `05_medium_fund_transfer_with_validation.sql:39-43` | `sp_transfer_funds` | CODE | Validation |
| BR-18 | Source balance must be at least the transfer amount | `05_medium_fund_transfer_with_validation.sql:78-80` | `sp_transfer_funds` | CODE | Limit-check |
| BR-19 | Both accounts must be ACTIVE to transfer | `05_medium_fund_transfer_with_validation.sql:59-61,74-76` | `sp_transfer_funds` | CODE | Validation |
| BR-20 | Today's cumulative TRANSFER_OUT plus this amount must not exceed the daily limit | `05_medium_fund_transfer_with_validation.sql:90-92` | `sp_transfer_funds` | CODE | Limit-check |

Additional DATABASE-enforced structural rules (primary keys, foreign keys, NOT NULL, defaults) are documented per table under [Data model](data-model/ddl-schema.md); BR-01 is called out here because it is a business-domain CHECK rather than a structural key.

## Rule records (machine-readable)

```json
{"id":"BR-01","statement":"Account status must be one of ACTIVE, DORMANT, CLOSED.","source_file":"00_ddl_create_schema.sql","source_lines":"69","expression":"CHECK (account_status IN ('ACTIVE','DORMANT','CLOSED'))","enforced_by":"ck_accounts_status","enforcement_type":"DATABASE","category":"Validation"}
```
```json
{"id":"BR-02","statement":"Principal amount must be greater than zero.","source_file":"01_simple_calculate_simple_interest.sql","source_lines":"19-21","expression":"IF p_principal IS NULL OR p_principal <= 0 THEN RAISE_APPLICATION_ERROR(-20001, 'Principal amount must be greater than zero.');","enforced_by":"fn_calculate_simple_interest","enforcement_type":"CODE","category":"Validation"}
```
```json
{"id":"BR-03","statement":"Interest rate cannot be negative (zero is allowed).","source_file":"01_simple_calculate_simple_interest.sql","source_lines":"23-25","expression":"IF p_annual_rate IS NULL OR p_annual_rate < 0 THEN RAISE_APPLICATION_ERROR(-20002, 'Interest rate cannot be negative.');","enforced_by":"fn_calculate_simple_interest","enforcement_type":"CODE","category":"Validation"}
```
```json
{"id":"BR-04","statement":"Tenure in days must be greater than zero.","source_file":"01_simple_calculate_simple_interest.sql","source_lines":"27-29","expression":"IF p_tenure_days IS NULL OR p_tenure_days <= 0 THEN RAISE_APPLICATION_ERROR(-20003, 'Tenure in days must be greater than zero.');","enforced_by":"fn_calculate_simple_interest","enforcement_type":"CODE","category":"Validation"}
```
```json
{"id":"BR-05","statement":"Day-count basis is 360 only when '360' is passed; every other value uses 365.","source_file":"01_simple_calculate_simple_interest.sql","source_lines":"32-36","expression":"IF p_day_count_basis = '360' THEN v_basis_days := 360; ELSE v_basis_days := 365; END IF;","enforced_by":"fn_calculate_simple_interest","enforcement_type":"CODE","category":"Routing"}
```
```json
{"id":"BR-06","statement":"Simple interest equals principal * rate * days / (100 * basis_days), rounded to 2 decimals.","source_file":"01_simple_calculate_simple_interest.sql","source_lines":"39-40","expression":"v_interest := ROUND( (p_principal * p_annual_rate * p_tenure_days) / (100 * v_basis_days), 2 );","enforced_by":"fn_calculate_simple_interest","enforcement_type":"CODE","category":"Calculation"}
```
```json
{"id":"BR-07","statement":"An ACTIVE account inactive for more than 365 days is marked DORMANT.","source_file":"02_simple_update_dormant_account_status.sql","source_lines":"27","expression":"IF v_days_inactive > 365 AND v_current_status = 'ACTIVE' THEN","enforced_by":"sp_update_dormant_account_status","enforcement_type":"CODE","category":"Limit-check"}
```
```json
{"id":"BR-08","statement":"A NULL last_transaction_date is treated as roughly 9999 days of inactivity.","source_file":"02_simple_update_dormant_account_status.sql","source_lines":"25","expression":"v_days_inactive := p_as_of_date - NVL(v_last_txn_date, p_as_of_date - 9999);","enforced_by":"sp_update_dormant_account_status","enforcement_type":"CODE","category":"Routing"}
```
```json
{"id":"BR-09","statement":"A DORMANT account whose inactivity is 365 days or fewer is reactivated to ACTIVE.","source_file":"02_simple_update_dormant_account_status.sql","source_lines":"37","expression":"ELSIF v_days_inactive <= 365 AND v_current_status = 'DORMANT' THEN","enforced_by":"sp_update_dormant_account_status","enforcement_type":"CODE","category":"Routing"}
```
```json
{"id":"BR-10","statement":"The below-minimum penalty is 5% of the shortfall, floored at 50 and capped at 500.","source_file":"03_simple_check_minimum_balance.sql","source_lines":"45","expression":"p_penalty_amount := LEAST(500, GREATEST(50, ROUND(p_shortfall_amount * 0.05, 2)));","enforced_by":"sp_check_minimum_balance","enforcement_type":"CODE","category":"Calculation"}
```
```json
{"id":"BR-11","statement":"A single account's failure during the interest batch is logged to batch_error_log and the batch continues with the next account.","source_file":"04_medium_process_monthly_interest_credit.sql","source_lines":"75-85","expression":"EXCEPTION WHEN OTHERS THEN INSERT INTO batch_error_log (...) VALUES (seq_log_id.NEXTVAL, 'MONTHLY_INTEREST_CREDIT', rec.account_number, SQLERRM, p_run_date); p_accounts_failed := p_accounts_failed + 1;","enforced_by":"sp_process_monthly_interest_credit","enforcement_type":"CODE","category":"Error-handling"}
```
```json
{"id":"BR-12","statement":"Monthly-credit interest rate is tiered by balance: <100000 -> 3.0%, <1000000 -> 3.5%, <10000000 -> 4.0%, else 4.5%.","source_file":"04_medium_process_monthly_interest_credit.sql","source_lines":"38-46","expression":"IF rec.balance < 100000 THEN v_interest_rate := 3.0; ELSIF rec.balance < 1000000 THEN v_interest_rate := 3.5; ELSIF rec.balance < 10000000 THEN v_interest_rate := 4.0; ELSE v_interest_rate := 4.5; END IF;","enforced_by":"sp_process_monthly_interest_credit","enforcement_type":"CODE","category":"Routing"}
```
```json
{"id":"BR-13","statement":"Monthly interest equals balance * (rate/100) * (days_in_month/365), rounded to 2 decimals.","source_file":"04_medium_process_monthly_interest_credit.sql","source_lines":"49-52","expression":"v_interest_amount := ROUND( rec.balance * (v_interest_rate / 100) * (v_days_in_month / 365), 2 );","enforced_by":"sp_process_monthly_interest_credit","enforcement_type":"CODE","category":"Calculation"}
```
```json
{"id":"BR-14","statement":"Only ACTIVE accounts whose account_type starts with SAVINGS are credited.","source_file":"04_medium_process_monthly_interest_credit.sql","source_lines":"19-21","expression":"WHERE account_status = 'ACTIVE' AND account_type LIKE 'SAVINGS%'","enforced_by":"sp_process_monthly_interest_credit","enforcement_type":"CODE","category":"Routing"}
```
```json
{"id":"BR-15","statement":"Interest is credited and a ledger row written only when the computed amount is greater than zero.","source_file":"04_medium_process_monthly_interest_credit.sql","source_lines":"54","expression":"IF v_interest_amount > 0 THEN","enforced_by":"sp_process_monthly_interest_credit","enforcement_type":"CODE","category":"Routing"}
```
```json
{"id":"BR-16","statement":"A transfer amount must be non-null and greater than zero.","source_file":"05_medium_fund_transfer_with_validation.sql","source_lines":"35-37","expression":"IF p_amount IS NULL OR p_amount <= 0 THEN RAISE e_invalid_amount;","enforced_by":"sp_transfer_funds","enforcement_type":"CODE","category":"Validation"}
```
```json
{"id":"BR-17","statement":"Source and destination accounts must not be the same.","source_file":"05_medium_fund_transfer_with_validation.sql","source_lines":"39-43","expression":"IF p_from_account = p_to_account THEN p_status := 'FAILED'; p_message := 'Source and destination accounts cannot be the same.'; RETURN;","enforced_by":"sp_transfer_funds","enforcement_type":"CODE","category":"Validation"}
```
```json
{"id":"BR-18","statement":"The source balance must be at least the transfer amount.","source_file":"05_medium_fund_transfer_with_validation.sql","source_lines":"78-80","expression":"IF v_from_balance < p_amount THEN RAISE e_insufficient_balance;","enforced_by":"sp_transfer_funds","enforcement_type":"CODE","category":"Limit-check"}
```
```json
{"id":"BR-19","statement":"Both source and destination accounts must be ACTIVE.","source_file":"05_medium_fund_transfer_with_validation.sql","source_lines":"59-61,74-76","expression":"IF v_from_status <> 'ACTIVE' THEN RAISE e_account_inactive; ... IF v_to_status <> 'ACTIVE' THEN RAISE e_account_inactive;","enforced_by":"sp_transfer_funds","enforcement_type":"CODE","category":"Validation"}
```
```json
{"id":"BR-20","statement":"Today's cumulative TRANSFER_OUT total plus this amount must not exceed the source's daily_transfer_limit.","source_file":"05_medium_fund_transfer_with_validation.sql","source_lines":"90-92","expression":"IF (v_today_txn_total + p_amount) > v_daily_limit THEN RAISE e_daily_limit_exceeded;","enforced_by":"sp_transfer_funds","enforcement_type":"CODE","category":"Limit-check"}
```

## Unverified observations

- The `account_type` and `txn_type` value lists appear only as DDL comments, not as CHECK constraints, so the database does **not** enforce them; they are conventions, not rules. See [`accounts`](data-model/tables/accounts.md) and [`transaction_ledger`](data-model/tables/transaction-ledger.md).
- The NPA bucket boundaries, fraud scoring thresholds, and amortization formula are described only in DDL/DML comments for the [absent programs 06-10](coverage-and-gaps.md); with no source code present they cannot be published as `BR-NN` rules.

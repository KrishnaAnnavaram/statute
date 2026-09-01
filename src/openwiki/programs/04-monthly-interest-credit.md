---
type: Procedure
title: "Program 04: sp_process_monthly_interest_credit"
description: Monthly batch that credits tiered interest to every active savings account, logs each credit to the ledger, and isolates per-account failures to batch_error_log without aborting the run.
resource: 04_medium_process_monthly_interest_credit.sql
tags: [program, procedure, batch, interest, cursor, medium]
---

# Program 04: `sp_process_monthly_interest_credit`

**Purpose (business terms):** run a monthly batch that calculates and credits interest to every active savings account using tiered rates based on balance, records each credit in the transaction ledger, and reports how many accounts were processed and failed.

Source file: [`04_medium_process_monthly_interest_credit.sql`](../../04_medium_process_monthly_interest_credit.sql) (category MEDIUM). Reads/writes [`accounts`](../data-model/tables/accounts.md); inserts into [`transaction_ledger`](../data-model/tables/transaction-ledger.md) and, on per-row failure, [`batch_error_log`](../data-model/tables/batch-error-log.md).

## Signature

| Parameter | Mode | Type | Meaning |
| --- | --- | --- | --- |
| `p_run_date` | IN | `DATE` default `SYSDATE` | The month/date the interest run is for; drives day count and ledger `txn_date`. |
| `p_accounts_processed` | OUT | `NUMBER` | Count of accounts successfully credited. |
| `p_accounts_failed` | OUT | `NUMBER` | Count of accounts whose credit failed and were logged. |

## Cursor

`c_savings_accounts` (lines 17-21) selects `account_number, customer_id, balance, account_type FROM accounts WHERE account_status = 'ACTIVE' AND account_type LIKE 'SAVINGS%'`. Only active savings-family accounts are credited ([BR-14](../business-rules.md)); the `SAVINGS%` filter is code-only, with no supporting DB constraint (see [coverage-and-gaps](../coverage-and-gaps.md)).

## Walkthrough (source order)

1. **Initialise counters** (lines 29-30): `p_accounts_processed := 0; p_accounts_failed := 0`.
2. **Days in month** (line 32): `v_days_in_month := EXTRACT(DAY FROM LAST_DAY(p_run_date))` — the calendar day count used to prorate interest.
3. **Loop over accounts** (line 34): `FOR rec IN c_savings_accounts LOOP`.
4. **Inner block start** (line 36): each iteration runs inside a nested `BEGIN ... EXCEPTION ... END` so a single-row failure cannot abort the batch.
5. **Tiered rate** (lines 38-46): `IF rec.balance < 100000 THEN 3.0; ELSIF < 1000000 THEN 3.5; ELSIF < 10000000 THEN 4.0; ELSE 4.5`. These slabs and rates are hard-coded ([BR-12](../business-rules.md)); they differ from [`interest_rate_master`](../data-model/tables/interest-rate-master.md) (see [coverage-and-gaps](../coverage-and-gaps.md)).
6. **Compute interest** (lines 49-52): `v_interest_amount := ROUND(rec.balance * (v_interest_rate / 100) * (v_days_in_month / 365), 2)` — annual rate prorated by days-in-month over 365. See [BR-13](../business-rules.md).
7. **Credit guard** (line 54): only proceed `IF v_interest_amount > 0` — no balance update or ledger row is written for a zero/negative computed amount. See [BR-15](../business-rules.md).
8. **Update balance** (lines 56-61): `v_new_balance := rec.balance + v_interest_amount`; `UPDATE accounts SET balance = v_new_balance, last_transaction_date = p_run_date WHERE account_number = rec.account_number`.
9. **Ledger insert** (lines 63-70): `INSERT INTO transaction_ledger (... txn_type='INT_CREDIT' ...) VALUES (seq_txn_id.NEXTVAL, ..., v_interest_amount, v_new_balance, 'Monthly interest credit @ ' || v_interest_rate || '%')`.
10. **Increment processed** (line 72): `p_accounts_processed := p_accounts_processed + 1`.
11. **Inner exception handler** (lines 75-85): `WHEN OTHERS` inserts a row into [`batch_error_log`](../data-model/tables/batch-error-log.md) (`batch_name='MONTHLY_INTEREST_CREDIT'`, `entity_key=rec.account_number`, `error_message=SQLERRM`) and increments `p_accounts_failed`. The loop then continues to the next account — the per-row isolation invariant ([BR-11](../business-rules.md)).
12. **Commit** (line 89): after the loop, `COMMIT` persists all balance updates, ledger rows, and error-log rows in one transaction.

## Transaction behaviour

All work — successful credits, ledger inserts, and error-log inserts — is committed together at line 89. If an error escapes the loop (the outer `WHEN OTHERS`, lines 91-95), the procedure `ROLLBACK`s **everything** (including error-log rows written this run) and raises `RAISE_APPLICATION_ERROR(-20010, 'sp_process_monthly_interest_credit failed: ' || SQLERRM)`. Note the consequence: because the commit is a single point at the end, an outer failure discards the entire run's work, and the `batch_error_log` rows written inside the loop are only durable if the run reaches the final `COMMIT`.

## Control flow

<!-- openwiki: mermaid parse failed and this diagram was converted to a text fence so it does not break rendering. Fix the diagram source and restore the mermaid fence. Parser error: Heuristic: an unescaped angle bracket inside a label breaks rendering; rephrase the label. -->
```text
flowchart TD
  START["compute days_in_month"] --> LOOP{"next active SAVINGS account?"}
  LOOP -->|yes| RATE["pick tiered rate by balance"]
  RATE --> CALC["interest = balance * rate/100 * days/365"]
  CALC --> POS{"interest > 0?"}
  POS -->|yes| UPD["UPDATE accounts balance + INSERT ledger INT_CREDIT"]
  UPD --> INC["processed++"]
  POS -->|no| LOOP
  INC --> LOOP
  RATE -.->|row error| LOG["INSERT batch_error_log, failed++"]
  UPD -.->|row error| LOG
  LOG --> LOOP
  LOOP -->|no more| COMMIT["COMMIT all work"]
  COMMIT --> DONE["return processed and failed counts"]
```
*Per-row failures branch to the error log and the loop continues; only the outer handler rolls back and raises -20010.*

## Exit paths

- **Normal completion:** all eligible accounts processed, `p_accounts_processed`/`p_accounts_failed` set, work committed.
- **`RAISE_APPLICATION_ERROR(-20010)`:** an error escaped the per-row handler; the whole run is rolled back and the error is raised to the caller.

## Sample data interaction

Active `SAVINGS%` accounts span all four tiers — e.g. `AC1000234575` at `6,500,000` hits the top `4.5%` slab; `AC1000234567` at `45000` hits `3.0%`. Dormant savings accounts (`AC1000234571`, `AC1000234577`) are excluded by the cursor filter. See [sample data](../data-model/dml-sample-data.md).

## Rules enforced

[BR-11](../business-rules.md) (Error-handling), [BR-12](../business-rules.md) (Routing), [BR-13](../business-rules.md) (Calculation), [BR-14](../business-rules.md) (Routing), [BR-15](../business-rules.md) (Routing). All CODE-enforced.

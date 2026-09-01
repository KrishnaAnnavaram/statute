---
type: Procedure
title: "Program 02: sp_update_dormant_account_status"
description: Marks a single account DORMANT after 365 days of inactivity, or reactivates a dormant account with recent activity, and reports the outcome via an OUT parameter.
resource: 02_simple_update_dormant_account_status.sql
tags: [program, procedure, accounts, dormancy, simple]
---

# Program 02: `sp_update_dormant_account_status`

**Purpose (business terms):** flip a single account to `DORMANT` when there has been no customer-initiated transaction for more than 365 days, or reactivate a dormant account whose last activity is now within 365 days.

Source file: [`02_simple_update_dormant_account_status.sql`](../../02_simple_update_dormant_account_status.sql) (category SIMPLE). Reads and writes [`accounts`](../data-model/tables/accounts.md).

## Signature

| Parameter | Mode | Type | Meaning |
| --- | --- | --- | --- |
| `p_account_number` | IN | `VARCHAR2` | Account to evaluate. |
| `p_as_of_date` | IN | `DATE` default `SYSDATE` | The date the dormancy is evaluated against. |
| `p_result` | OUT | `VARCHAR2` | Outcome code (see exit paths). |

## Preconditions

The account should exist; a missing account is handled gracefully (see exit paths). The dormancy threshold and reactivation both compare against `p_as_of_date`.

## Walkthrough (source order)

1. **Fetch state** (lines 20-23): `SELECT last_transaction_date, account_status INTO v_last_txn_date, v_current_status FROM accounts WHERE account_number = p_account_number`. A missing row raises `NO_DATA_FOUND`, caught below.
2. **Compute inactivity** (line 25): `v_days_inactive := p_as_of_date - NVL(v_last_txn_date, p_as_of_date - 9999)`. The `NVL(..., p_as_of_date - 9999)` guard means a NULL `last_transaction_date` is treated as ~9999 days inactive, so a never-transacted account is considered dormant. See [BR-08](../business-rules.md).
3. **Dormancy branch** (lines 27-36): if `v_days_inactive > 365 AND v_current_status = 'ACTIVE'`, `UPDATE accounts SET account_status = 'DORMANT', status_change_date = p_as_of_date, last_modified_by = 'SYSTEM_BATCH'`; set `p_result := 'ACCOUNT_MARKED_DORMANT'`. The `> 365` threshold is the dormancy rule ([BR-07](../business-rules.md)).
4. **Reactivation branch** (lines 37-46): else if `v_days_inactive <= 365 AND v_current_status = 'DORMANT'`, `UPDATE accounts SET account_status = 'ACTIVE', ...`; set `p_result := 'ACCOUNT_REACTIVATED'`. See [BR-09](../business-rules.md). Note the gap between intent and logic: the source comment (line 39) says "Reactivate if a transaction has occurred recently," but the branch fires purely on `last_transaction_date` being within 365 days of `p_as_of_date` — it does **not** confirm a *new* transaction happened. If `last_transaction_date` already sat within the window when the account was made dormant, this procedure would reactivate it on the next run without any new activity.
5. **No-change branch** (lines 48-50): otherwise set `p_result := 'NO_STATUS_CHANGE_REQUIRED'` (e.g. active-and-recent, or already dormant-and-still-inactive).
6. **Commit** (line 52): `COMMIT` persists any update.

## Transaction behaviour

`COMMIT` on the normal path (line 52). On `WHEN OTHERS` the procedure `ROLLBACK`s (line 58) to undo a partial update, then re-raises. `NO_DATA_FOUND` neither commits nor rolls back — no DML has occurred.

## Exit paths

- `p_result = 'ACCOUNT_MARKED_DORMANT'` — account was active and inactive `> 365` days; now DORMANT (committed).
- `p_result = 'ACCOUNT_REACTIVATED'` — account was dormant and is now within 365 days; now ACTIVE (committed).
- `p_result = 'NO_STATUS_CHANGE_REQUIRED'` — no update needed (committed, but no rows changed).
- `p_result = 'ACCOUNT_NOT_FOUND'` — `WHEN NO_DATA_FOUND` (lines 55-56); no exception propagates.
- `p_result = 'ERROR: ' || SQLERRM` **and re-raise** — `WHEN OTHERS` (lines 57-60): sets the message, `ROLLBACK`, then `RAISE`. The caller both sees the message and receives the propagated exception.

## Sample data interaction

Accounts `AC1000234571` and `AC1000234577` are seeded `DORMANT` with 2024 `last_transaction_date`s; evaluated as of the `2026-06-30` reference date they remain inactive `> 365` days and stay dormant. See [sample data](../data-model/dml-sample-data.md).

## Rules enforced

[BR-07](../business-rules.md) (Routing/Limit-check), [BR-08](../business-rules.md), [BR-09](../business-rules.md). All CODE-enforced. The `account_status` value written is also bounded by the DATABASE CHECK [BR-01](../business-rules.md).

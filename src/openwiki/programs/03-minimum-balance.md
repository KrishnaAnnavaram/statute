---
type: Procedure
title: "Program 03: sp_check_minimum_balance"
description: Read-only check of an account balance against its account-type minimum, returning the shortfall and a capped/floored penalty. No DML.
resource: 03_simple_check_minimum_balance.sql
tags: [program, procedure, accounts, minimum-balance, penalty, simple]
---

# Program 03: `sp_check_minimum_balance`

**Purpose (business terms):** determine whether an account is below the minimum balance required for its type, and compute the penalty charge if it is.

Source file: [`03_simple_check_minimum_balance.sql`](../../03_simple_check_minimum_balance.sql) (category SIMPLE). It **reads** [`accounts`](../data-model/tables/accounts.md) and performs **no DML** — it computes and returns values only.

## Signature

| Parameter | Mode | Type | Meaning |
| --- | --- | --- | --- |
| `p_account_number` | IN | `VARCHAR2` | Account to check. |
| `p_penalty_amount` | OUT | `NUMBER` | Penalty charge (0 if compliant, `NULL` if not found). |
| `p_shortfall_amount` | OUT | `NUMBER` | Amount below the minimum (0 if compliant, `NULL` if not found). |
| `p_message` | OUT | `VARCHAR2` | Outcome code (see exit paths). |

## Preconditions

The account should exist; a missing account returns `ACCOUNT_NOT_FOUND` without raising.

## Walkthrough (source order)

1. **Fetch balance and type** (lines 21-24): `SELECT balance, account_type INTO v_current_balance, v_account_type FROM accounts WHERE account_number = p_account_number`. Missing row → `NO_DATA_FOUND`.
2. **Resolve minimum by account type** (lines 27-35): a `CASE v_account_type` returns the required minimum — `SAVINGS_REGULAR` → 1000, `SAVINGS_PREMIUM` → 10000, `SAVINGS_ZERO_BAL` → 0, `CURRENT_REGULAR` → 5000, `CURRENT_PREMIUM` → 25000, `ELSE` → 1000. These thresholds are hard-coded in code (see [BR-10](../business-rules.md) and the [coverage note](../coverage-and-gaps.md)).
3. **Compliant branch** (lines 37-40): if `v_current_balance >= v_min_balance_req`, set `p_shortfall_amount := 0`, `p_penalty_amount := 0`, `p_message := 'BALANCE_OK'`.
4. **Shortfall branch** (lines 41-47): else compute `p_shortfall_amount := v_min_balance_req - v_current_balance`, then `p_penalty_amount := LEAST(500, GREATEST(50, ROUND(p_shortfall_amount * 0.05, 2)))` — 5% of the shortfall, **floored at 50 and capped at 500** — and `p_message := 'BELOW_MINIMUM_BALANCE'`. See [BR-10](../business-rules.md).

## Transaction behaviour

None. The procedure performs no DML and issues no `COMMIT`/`ROLLBACK`.

## Exit paths

- `p_message = 'BALANCE_OK'`, penalty and shortfall both `0` — compliant.
- `p_message = 'BELOW_MINIMUM_BALANCE'`, with computed shortfall and penalty — below minimum.
- `p_message = 'ACCOUNT_NOT_FOUND'`, penalty and shortfall `NULL` — `WHEN NO_DATA_FOUND` (lines 50-53); no exception propagates.
- `p_message = 'ERROR: ' || SQLERRM` **and re-raise** — `WHEN OTHERS` (lines 54-56): sets the message then `RAISE`.

## Sample data interaction

Account `AC1000234570` (`CURRENT_REGULAR`, balance `3200`) is below its `5000` minimum, yielding a `1800` shortfall and a `90` penalty (5% of 1800, within the 50-500 band). See [sample data](../data-model/dml-sample-data.md).

## Rules enforced

[BR-10](../business-rules.md) (Calculation/Limit-check), CODE-enforced. The minimum thresholds are hard-coded rather than read from a reference table — recorded in [coverage-and-gaps](../coverage-and-gaps.md).

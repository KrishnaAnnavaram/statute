---
type: Function
title: "Program 01: fn_calculate_simple_interest"
description: Pure function computing simple interest on a principal for a tenure in days, with 360/365 day-count basis and input validation. No table access.
resource: 01_simple_calculate_simple_interest.sql
tags: [program, function, interest, calculation, simple]
---

# Program 01: `fn_calculate_simple_interest`

**Purpose (business terms):** compute the simple interest owed on a principal amount over a number of days, for a fixed deposit or short-term loan.

Source file: [`01_simple_calculate_simple_interest.sql`](../../01_simple_calculate_simple_interest.sql) (category SIMPLE). It is a **pure function** — it reads and writes no tables and never commits.

## Signature

| Parameter | Mode | Type | Meaning |
| --- | --- | --- | --- |
| `p_principal` | IN | `NUMBER` | Principal amount. Must be `> 0`. |
| `p_annual_rate` | IN | `NUMBER` | Annual interest rate as a percentage (e.g. `7.5` means 7.5%). Must be `>= 0`. |
| `p_tenure_days` | IN | `NUMBER` | Tenure in days. Must be `> 0`. |
| `p_day_count_basis` | IN | `VARCHAR2` default `'365'` | Day-count basis: `'360'` or `'365'`. Any value other than `'360'` is treated as 365. |
| *(return)* | — | `NUMBER` | The computed interest, rounded to 2 decimals. |

## Preconditions

The caller must pass a positive principal, a non-negative rate, and a positive tenure; otherwise the function raises. There are no schema preconditions since no tables are read.

## Walkthrough (source order)

1. **Validate principal** (lines 19-21): if `p_principal IS NULL OR p_principal <= 0`, raise `RAISE_APPLICATION_ERROR(-20001, 'Principal amount must be greater than zero.')`. See [BR-02](../business-rules.md).
2. **Validate rate** (lines 23-25): if `p_annual_rate IS NULL OR p_annual_rate < 0`, raise `-20002` ("Interest rate cannot be negative."). See [BR-03](../business-rules.md). Note zero rate is permitted.
3. **Validate tenure** (lines 27-29): if `p_tenure_days IS NULL OR p_tenure_days <= 0`, raise `-20003` ("Tenure in days must be greater than zero."). See [BR-04](../business-rules.md).
4. **Resolve day-count basis** (lines 32-36): `IF p_day_count_basis = '360' THEN v_basis_days := 360; ELSE v_basis_days := 365; END IF;`. The `ELSE` makes 365 the effective default for any non-`'360'` value. See [BR-05](../business-rules.md).
5. **Compute interest** (lines 39-40): `v_interest := ROUND((p_principal * p_annual_rate * p_tenure_days) / (100 * v_basis_days), 2)`. This is `P * R * T / (100 * basis)`, rounded to 2 decimals. See [BR-06](../business-rules.md).
6. **Return** (line 42): return `v_interest`.

## Transaction behaviour

None. The function performs no DML, so there is nothing to commit or roll back.

## Exit paths

- **Normal return:** the rounded interest value.
- **`RAISE_APPLICATION_ERROR(-20001/-20002/-20003)`:** on invalid principal, rate, or tenure respectively. The caller receives an ORA-2000x error.
- **`WHEN OTHERS`** (lines 44-47): echoes `'Error in fn_calculate_simple_interest: ' || SQLERRM` via `DBMS_OUTPUT.PUT_LINE` and then `RAISE` — the original exception propagates to the caller unchanged.

## Sample usage

```sql
SELECT fn_calculate_simple_interest(100000, 7.5, 180, '365') AS interest_amount FROM dual;
```

## Rules enforced

[BR-02](../business-rules.md), [BR-03](../business-rules.md), [BR-04](../business-rules.md) (Validation); [BR-05](../business-rules.md), [BR-06](../business-rules.md) (Calculation). All CODE-enforced.

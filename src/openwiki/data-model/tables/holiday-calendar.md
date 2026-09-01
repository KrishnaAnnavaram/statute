---
type: Table
title: "Table: holiday_calendar"
description: National/regional holiday dates used by the absent EOD accrual program #8 to skip batch runs on holidays. Seeded with sample data; no present program reads it.
resource: 00_ddl_create_schema.sql
tags: [table, holiday-calendar, operational, orphan]
---

# Table: `holiday_calendar`

Calendar of holiday dates. Defined at `00_ddl_create_schema.sql` lines 206-211. The DDL header comment states it is **"used by #8 to skip EOD batch on holidays"** — the absent end-of-day accrual program.

## Columns

| Column | Type | Nullability | Meaning |
| --- | --- | --- | --- |
| `holiday_date` | `DATE` | NOT NULL | The holiday date. Part of PK. |
| `calendar_type` | `VARCHAR2(20)` | NOT NULL | `NATIONAL` or `REGIONAL`. Part of PK. |
| `description` | `VARCHAR2(100)` | nullable | Human-readable name of the holiday. |

## Constraints

- `pk_holiday_calendar` PRIMARY KEY (`holiday_date`, `calendar_type`) — ENABLED, VALIDATED.

## Programs that read or write it

**None in this checkout.** It is a reference table for the absent accrual program (#8). It is an **orphan** in the present programs. See [coverage-and-gaps](../../coverage-and-gaps.md).

## Sample data

Three national holidays for 2026 — Republic Day, Independence Day, Gandhi Jayanti (`00_dml_load_sample_schema.sql` lines 177-182). See [sample data](../dml-sample-data.md).

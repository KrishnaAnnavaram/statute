# Files

- [Program 01: fn_calculate_simple_interest](01-simple-interest.md) - Pure function computing simple interest on a principal for a tenure in days, with 360/365 day-count basis and input validation. No table access.
- [Program 02: sp_update_dormant_account_status](02-dormant-account-status.md) - Marks a single account DORMANT after 365 days of inactivity, or reactivates a dormant account with recent activity, and reports the outcome via an OUT parameter.
- [Program 03: sp_check_minimum_balance](03-minimum-balance.md) - Read-only check of an account balance against its account-type minimum, returning the shortfall and a capped/floored penalty. No DML.
- [Program 04: sp_process_monthly_interest_credit](04-monthly-interest-credit.md) - Monthly batch that credits tiered interest to every active savings account, logs each credit to the ledger, and isolates per-account failures to batch_error_log without aborting the run.
- [Program 05: sp_transfer_funds](05-fund-transfer.md) - Validated inter-account transfer - existence, status, balance, and daily-limit checks with row locking, savepoint rollback, and atomic debit/credit both logged to the ledger.
- [Programs Overview](overview.md) - The five present PL/SQL programs - complexity tiers, common patterns, error codes, and the tables each reads or writes. Notes the absent programs 06-10 the schema references.

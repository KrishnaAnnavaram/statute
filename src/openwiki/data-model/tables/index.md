# Files

- [Table: accounts](accounts.md) - One row per deposit/overdraft account - balance, type, status, and daily transfer limit. The central table read or written by four of the five present programs.
- [Table: batch_control_log](batch-control-log.md) - Generic batch-run control table (run id, timings, counts, control totals). Defined in the DDL but not read or written by any program present in this checkout.
- [Table: batch_error_log](batch-error-log.md) - Generic per-row batch failure log. Written by the monthly interest-credit program to record account-level errors without aborting the batch.
- [Table: customers](customers.md) - Master record for each banking customer - identity, KYC status, and relationship start date. Parent of accounts and loan_master.
- [Table: fraud_score_results](fraud-score-results.md) - Per-transaction fraud risk scores and reasons - output of the absent fraud-scoring program
- [Table: holiday_calendar](holiday-calendar.md) - National/regional holiday dates used by the absent EOD accrual program
- [Table: interest_accrual_ledger](interest-accrual-ledger.md) - Daily interest-accrual entries per account (accrued amount, applied rate, posted flag) - output of the absent EOD accrual program
- [Table: interest_rate_master](interest-rate-master.md) - Reference table of annual rates by product code and balance slab. Intended for the absent EOD accrual program
- [Table: loan_amortization_schedule](loan-amortization-schedule.md) - Per-installment EMI breakdown (opening balance, interest, principal, closing balance) - the output of the absent amortization program
- [Table: loan_master](loan-master.md) - One row per loan account - principal, outstanding balance, rate, tenure, collateral, and restructure flag. Parent of the loan history/schedule/tracker tables.
- [Table: loan_rate_reset_history](loan-rate-reset-history.md) - Floating-rate reset events for a loan - the installment number a revised annual rate takes effect from. Populated as sample data; no present program reads or writes it.
- [Table: loan_repayment_tracker](loan-repayment-tracker.md) - Days-past-due snapshot per loan and as-of-date - the input to the absent NPA-classification program
- [Table: npa_classification_history](npa-classification-history.md) - Per-loan, per-date NPA classification with provisioning amount and movement type - output of the absent NPA program
- [Table: npa_provisioning_summary](npa-provisioning-summary.md) - Quarter-end control total - total accounts and total provisioning across all loans. Output of the absent NPA program
- [Table: transaction_ledger](transaction-ledger.md) - Append-only ledger of every account transaction - type, amount, running balance, and fraud-relevant fields. Written by the interest-credit and fund-transfer programs.

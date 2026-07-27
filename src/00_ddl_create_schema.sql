/*==============================================================================
  Program   : 00_ddl_create_schema.sql
  Purpose   : DDL for all sequences and tables referenced by the 10 sample
              PL/SQL programs (01 through 10). Run this script first, before
              loading sample data or compiling the procedures/functions.
  Target    : Oracle Database (12c+ recommended for IDENTITY/analytic support,
              though sequences are used here for broad compatibility).
==============================================================================*/

-- Uncomment if re-running against an existing schema, in dependency order:
-- DROP TABLE npa_provisioning_summary PURGE;
-- DROP TABLE npa_classification_history PURGE;
-- DROP TABLE loan_repayment_tracker PURGE;
-- DROP TABLE fraud_score_results PURGE;
-- DROP TABLE holiday_calendar PURGE;
-- DROP TABLE interest_accrual_ledger PURGE;
-- DROP TABLE interest_rate_master PURGE;
-- DROP TABLE loan_amortization_schedule PURGE;
-- DROP TABLE loan_rate_reset_history PURGE;
-- DROP TABLE loan_master PURGE;
-- DROP TABLE batch_control_log PURGE;
-- DROP TABLE batch_error_log PURGE;
-- DROP TABLE transaction_ledger PURGE;
-- DROP TABLE accounts PURGE;
-- DROP TABLE customers PURGE;
-- DROP SEQUENCE seq_txn_id;
-- DROP SEQUENCE seq_log_id;
-- DROP SEQUENCE seq_batch_run_id;

-----------------------------------------------------------------------------
-- SEQUENCES
-----------------------------------------------------------------------------
CREATE SEQUENCE seq_txn_id        START WITH 100001 INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE seq_log_id        START WITH 1      INCREMENT BY 1 NOCACHE;
CREATE SEQUENCE seq_batch_run_id  START WITH 1      INCREMENT BY 1 NOCACHE;

-----------------------------------------------------------------------------
-- CUSTOMERS
-----------------------------------------------------------------------------
CREATE TABLE customers (
    customer_id           VARCHAR2(20)   NOT NULL,
    customer_name          VARCHAR2(150) NOT NULL,
    date_of_birth           DATE,
    registered_country      VARCHAR2(3)   NOT NULL,   -- ISO country code
    kyc_status               VARCHAR2(20)  DEFAULT 'VERIFIED',
    customer_since_date      DATE          DEFAULT SYSDATE,
    CONSTRAINT pk_customers PRIMARY KEY (customer_id)
);

-----------------------------------------------------------------------------
-- ACCOUNTS  (savings / current / term deposit / overdraft)
-----------------------------------------------------------------------------
CREATE TABLE accounts (
    account_number         VARCHAR2(20)   NOT NULL,
    customer_id             VARCHAR2(20)   NOT NULL,
    account_type             VARCHAR2(20)   NOT NULL,  -- SAVINGS_REGULAR, SAVINGS_PREMIUM,
                                                          -- SAVINGS_ZERO_BAL, CURRENT_REGULAR,
                                                          -- CURRENT_PREMIUM, TERM_DEPOSIT, OVERDRAFT
    balance                   NUMBER(18,2)   DEFAULT 0 NOT NULL,
    account_status            VARCHAR2(20)   DEFAULT 'ACTIVE' NOT NULL,  -- ACTIVE, DORMANT, CLOSED
    daily_transfer_limit      NUMBER(18,2)   DEFAULT 500000,
    last_transaction_date     DATE,
    status_change_date        DATE,
    last_modified_by          VARCHAR2(50),
    account_open_date         DATE           DEFAULT SYSDATE,
    CONSTRAINT pk_accounts PRIMARY KEY (account_number),
    CONSTRAINT fk_accounts_customer FOREIGN KEY (customer_id)
        REFERENCES customers (customer_id),
    CONSTRAINT ck_accounts_status CHECK (account_status IN ('ACTIVE','DORMANT','CLOSED'))
);

-----------------------------------------------------------------------------
-- TRANSACTION_LEDGER
-----------------------------------------------------------------------------
CREATE TABLE transaction_ledger (
    txn_id                 NUMBER         NOT NULL,
    account_number          VARCHAR2(20)   NOT NULL,
    txn_date                  DATE           DEFAULT SYSDATE NOT NULL,
    txn_type                   VARCHAR2(20)   NOT NULL,  -- TRANSFER_IN, TRANSFER_OUT, INT_CREDIT,
                                                           -- DEPOSIT, WITHDRAWAL, FEE, CHARGE,
                                                           -- EMI_DEBIT, SALARY_CREDIT
    txn_amount                 NUMBER(18,2)   NOT NULL,
    running_balance             NUMBER(18,2),
    reference_number            VARCHAR2(50),
    narration                    VARCHAR2(200),
    origin_country                VARCHAR2(3),
    beneficiary_id                VARCHAR2(20),
    hold_flag                      VARCHAR2(1)   DEFAULT 'N',
    CONSTRAINT pk_transaction_ledger PRIMARY KEY (txn_id),
    CONSTRAINT fk_txn_account FOREIGN KEY (account_number)
        REFERENCES accounts (account_number)
);

CREATE INDEX idx_txn_ledger_acct_date ON transaction_ledger (account_number, txn_date);

-----------------------------------------------------------------------------
-- BATCH_ERROR_LOG  /  BATCH_CONTROL_LOG   (generic batch-job audit tables)
-----------------------------------------------------------------------------
CREATE TABLE batch_error_log (
    log_id            NUMBER          NOT NULL,
    batch_name         VARCHAR2(50)    NOT NULL,
    entity_key          VARCHAR2(50),
    error_message         VARCHAR2(1000),
    log_date               DATE          DEFAULT SYSDATE,
    CONSTRAINT pk_batch_error_log PRIMARY KEY (log_id)
);

CREATE TABLE batch_control_log (
    batch_run_id       NUMBER          NOT NULL,
    batch_name           VARCHAR2(50)    NOT NULL,
    business_date          DATE           NOT NULL,
    start_time               TIMESTAMP,
    end_time                   TIMESTAMP,
    status                       VARCHAR2(20)  DEFAULT 'RUNNING',
    records_processed             NUMBER,
    records_failed                  NUMBER,
    control_total                     NUMBER(20,2),
    error_message                       VARCHAR2(1000),
    CONSTRAINT pk_batch_control_log PRIMARY KEY (batch_run_id)
);

-----------------------------------------------------------------------------
-- LOAN_MASTER
-----------------------------------------------------------------------------
CREATE TABLE loan_master (
    loan_account_number      VARCHAR2(20)   NOT NULL,
    customer_id                VARCHAR2(20)   NOT NULL,
    loan_type                    VARCHAR2(20)   NOT NULL,  -- HOME_LOAN, AUTO_LOAN, PERSONAL_LOAN,
                                                              -- EDUCATION_LOAN, MORTGAGE
    principal_amount               NUMBER(18,2)   NOT NULL,
    outstanding_principal            NUMBER(18,2)   NOT NULL,
    annual_interest_rate               NUMBER(6,3)    NOT NULL,
    tenure_months                        NUMBER         NOT NULL,
    disbursement_date                      DATE           NOT NULL,
    rate_reset_frequency_months              NUMBER         DEFAULT 0,  -- 0 = fixed rate
    collateral_value                           NUMBER(18,2)   DEFAULT 0,
    is_restructured                              VARCHAR2(1)    DEFAULT 'N',
    restructure_date                               DATE,
    loan_status                                      VARCHAR2(20)   DEFAULT 'ACTIVE',
    CONSTRAINT pk_loan_master PRIMARY KEY (loan_account_number),
    CONSTRAINT fk_loan_customer FOREIGN KEY (customer_id)
        REFERENCES customers (customer_id)
);

-----------------------------------------------------------------------------
-- LOAN_RATE_RESET_HISTORY   (floating-rate reset events)
-----------------------------------------------------------------------------
CREATE TABLE loan_rate_reset_history (
    loan_account_number        VARCHAR2(20)   NOT NULL,
    effective_installment_no     NUMBER         NOT NULL,
    revised_annual_rate            NUMBER(6,3)    NOT NULL,
    reset_date                       DATE           DEFAULT SYSDATE,
    CONSTRAINT pk_loan_rate_reset PRIMARY KEY (loan_account_number, effective_installment_no),
    CONSTRAINT fk_rate_reset_loan FOREIGN KEY (loan_account_number)
        REFERENCES loan_master (loan_account_number)
);

-----------------------------------------------------------------------------
-- LOAN_AMORTIZATION_SCHEDULE   (output of program #7)
-----------------------------------------------------------------------------
CREATE TABLE loan_amortization_schedule (
    loan_account_number       VARCHAR2(20)   NOT NULL,
    installment_no               NUMBER         NOT NULL,
    due_date                       DATE           NOT NULL,
    opening_balance                   NUMBER(18,2)   NOT NULL,
    emi_amount                          NUMBER(18,2)   NOT NULL,
    interest_component                    NUMBER(18,2)   NOT NULL,
    principal_component                     NUMBER(18,2)   NOT NULL,
    closing_balance                            NUMBER(18,2)   NOT NULL,
    CONSTRAINT pk_loan_amort_sched PRIMARY KEY (loan_account_number, installment_no),
    CONSTRAINT fk_amort_sched_loan FOREIGN KEY (loan_account_number)
        REFERENCES loan_master (loan_account_number)
);

-----------------------------------------------------------------------------
-- INTEREST_RATE_MASTER   (product/balance-slab rate lookup, used by #8)
-----------------------------------------------------------------------------
CREATE TABLE interest_rate_master (
    product_code         VARCHAR2(20)   NOT NULL,
    min_balance             NUMBER(18,2)   DEFAULT 0 NOT NULL,
    max_balance                NUMBER(18,2),                      -- NULL = no upper bound
    annual_rate                   NUMBER(6,3)    NOT NULL,
    effective_date                   DATE           NOT NULL,
    CONSTRAINT pk_interest_rate_master
        PRIMARY KEY (product_code, min_balance, effective_date)
);

-----------------------------------------------------------------------------
-- INTEREST_ACCRUAL_LEDGER   (output of program #8)
-----------------------------------------------------------------------------
CREATE TABLE interest_accrual_ledger (
    account_number       VARCHAR2(20)   NOT NULL,
    accrual_date            DATE           NOT NULL,
    accrued_amount             NUMBER(18,4)   NOT NULL,
    applied_rate                  NUMBER(6,3),
    posted_flag                     VARCHAR2(1)    DEFAULT 'N',
    last_updated                       TIMESTAMP     DEFAULT SYSTIMESTAMP,
    CONSTRAINT pk_interest_accrual_ledger PRIMARY KEY (account_number, accrual_date),
    CONSTRAINT fk_accrual_account FOREIGN KEY (account_number)
        REFERENCES accounts (account_number)
);

-----------------------------------------------------------------------------
-- HOLIDAY_CALENDAR   (used by #8 to skip EOD batch on holidays)
-----------------------------------------------------------------------------
CREATE TABLE holiday_calendar (
    holiday_date        DATE           NOT NULL,
    calendar_type          VARCHAR2(20)   NOT NULL,   -- NATIONAL, REGIONAL
    description               VARCHAR2(100),
    CONSTRAINT pk_holiday_calendar PRIMARY KEY (holiday_date, calendar_type)
);

-----------------------------------------------------------------------------
-- FRAUD_SCORE_RESULTS   (output of program #9)
-----------------------------------------------------------------------------
CREATE TABLE fraud_score_results (
    txn_id             NUMBER         NOT NULL,
    account_number        VARCHAR2(20)   NOT NULL,
    txn_amount               NUMBER(18,2)   NOT NULL,
    risk_score                  NUMBER(5,0)    DEFAULT 0,
    risk_reasons                   VARCHAR2(4000),
    scored_date                       TIMESTAMP     DEFAULT SYSTIMESTAMP,
    CONSTRAINT pk_fraud_score_results PRIMARY KEY (txn_id)
);

-----------------------------------------------------------------------------
-- LOAN_REPAYMENT_TRACKER   (days-past-due snapshot feeding NPA classification, #10)
-----------------------------------------------------------------------------
CREATE TABLE loan_repayment_tracker (
    loan_account_number     VARCHAR2(20)   NOT NULL,
    as_of_date                 DATE           NOT NULL,
    days_past_due                 NUMBER         DEFAULT 0,
    last_payment_date                DATE,
    last_payment_amount                 NUMBER(18,2),
    CONSTRAINT pk_loan_repayment_tracker PRIMARY KEY (loan_account_number, as_of_date),
    CONSTRAINT fk_repay_tracker_loan FOREIGN KEY (loan_account_number)
        REFERENCES loan_master (loan_account_number)
);

-----------------------------------------------------------------------------
-- NPA_CLASSIFICATION_HISTORY   (output of program #10)
-----------------------------------------------------------------------------
CREATE TABLE npa_classification_history (
    loan_account_number      VARCHAR2(20)   NOT NULL,
    classification_date         DATE           NOT NULL,
    classification                  VARCHAR2(20)   NOT NULL, -- STANDARD, SPECIAL_MENTION,
                                                                -- SUBSTANDARD, DOUBTFUL, LOSS
    days_past_due                      NUMBER,
    outstanding_principal                 NUMBER(18,2),
    collateral_cover_pct                     NUMBER(6,2),
    provisioning_amount                        NUMBER(18,2),
    prior_classification                          VARCHAR2(20),
    movement_type                                    VARCHAR2(20),  -- NEW, UNCHANGED, UPGRADED, DOWNGRADED
    CONSTRAINT pk_npa_class_hist PRIMARY KEY (loan_account_number, classification_date)
);

-----------------------------------------------------------------------------
-- NPA_PROVISIONING_SUMMARY   (quarter-end control total, output of #10)
-----------------------------------------------------------------------------
CREATE TABLE npa_provisioning_summary (
    quarter_end_date          DATE           NOT NULL,
    total_accounts               NUMBER,
    total_provisioning_amount       NUMBER(20,2),
    run_timestamp                      TIMESTAMP     DEFAULT SYSTIMESTAMP,
    CONSTRAINT pk_npa_provisioning_summary PRIMARY KEY (quarter_end_date)
);

COMMIT;
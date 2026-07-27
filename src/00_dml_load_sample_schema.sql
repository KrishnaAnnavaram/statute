/*==============================================================================
  Program   : 00_dml_load_sample_data.sql
  Purpose   : Sample data for all tables created in 00_ddl_create_schema.sql.
              Data is deliberately shaped to exercise the branching logic in
              every one of the 10 PL/SQL sample programs (dormant accounts,
              below-minimum-balance accounts, tiered interest slabs, a
              restructured loan, a floating-rate loan, fraud-rule triggers,
              and loans across every NPA bucket).
  Run order : Run AFTER 00_ddl_create_schema.sql and AFTER compiling the
              10 procedures/functions (some DML below simulates what the
              procedures would otherwise generate, to give the team a
              baseline dataset to diff against).
  Reference date used throughout: 30-JUN-2026 (a quarter-end / month-end date)
==============================================================================*/

-----------------------------------------------------------------------------
-- CUSTOMERS
-----------------------------------------------------------------------------
INSERT INTO customers (customer_id, customer_name, date_of_birth, registered_country, kyc_status, customer_since_date) VALUES
('CUST00001', 'Arjun Mehta',        DATE '1985-04-12', 'IND', 'VERIFIED', DATE '2015-06-01');
INSERT INTO customers (customer_id, customer_name, date_of_birth, registered_country, kyc_status, customer_since_date) VALUES
('CUST00002', 'Priya Nair',         DATE '1990-11-23', 'IND', 'VERIFIED', DATE '2017-02-14');
INSERT INTO customers (customer_id, customer_name, date_of_birth, registered_country, kyc_status, customer_since_date) VALUES
('CUST00003', 'Rahul Verma',        DATE '1978-07-30', 'IND', 'VERIFIED', DATE '2012-09-10');
INSERT INTO customers (customer_id, customer_name, date_of_birth, registered_country, kyc_status, customer_since_date) VALUES
('CUST00004', 'Sara Thomas',        DATE '1995-01-05', 'GBR', 'VERIFIED', DATE '2019-03-22');
INSERT INTO customers (customer_id, customer_name, date_of_birth, registered_country, kyc_status, customer_since_date) VALUES
('CUST00005', 'Michael Chen',       DATE '1982-09-17', 'SGP', 'VERIFIED', DATE '2016-05-18');
INSERT INTO customers (customer_id, customer_name, date_of_birth, registered_country, kyc_status, customer_since_date) VALUES
('CUST00006', 'Fatima Al-Sayed',    DATE '1988-03-02', 'ARE', 'VERIFIED', DATE '2018-11-30');
INSERT INTO customers (customer_id, customer_name, date_of_birth, registered_country, kyc_status, customer_since_date) VALUES
('CUST00007', 'David Okafor',       DATE '1975-12-19', 'USA', 'VERIFIED', DATE '2010-01-15');
INSERT INTO customers (customer_id, customer_name, date_of_birth, registered_country, kyc_status, customer_since_date) VALUES
('CUST00008', 'Lena Schmidt',       DATE '1992-06-08', 'DEU', 'VERIFIED', DATE '2020-07-07');

-----------------------------------------------------------------------------
-- ACCOUNTS
-- Mix of types/statuses to exercise: dormancy (02), min-balance shortfall (03),
-- tiered interest slabs (04), transfer validation (05), statements (06).
-----------------------------------------------------------------------------
INSERT INTO accounts (account_number, customer_id, account_type, balance, account_status, daily_transfer_limit, last_transaction_date, account_open_date) VALUES
('AC1000234567', 'CUST00001', 'SAVINGS_REGULAR', 45000.00,  'ACTIVE',  200000, DATE '2026-06-25', DATE '2015-06-05');
INSERT INTO accounts (account_number, customer_id, account_type, balance, account_status, daily_transfer_limit, last_transaction_date, account_open_date) VALUES
('AC1000234568', 'CUST00001', 'TERM_DEPOSIT',    500000.00, 'ACTIVE',  0,      DATE '2026-01-10', DATE '2024-01-10');
INSERT INTO accounts (account_number, customer_id, account_type, balance, account_status, daily_transfer_limit, last_transaction_date, account_open_date) VALUES
('AC1000234569', 'CUST00002', 'SAVINGS_PREMIUM', 1250000.00,'ACTIVE',  1000000,DATE '2026-06-30', DATE '2017-02-20');
INSERT INTO accounts (account_number, customer_id, account_type, balance, account_status, daily_transfer_limit, last_transaction_date, account_open_date) VALUES
('AC1000234570', 'CUST00002', 'CURRENT_REGULAR', 3200.00,   'ACTIVE',  300000, DATE '2026-06-28', DATE '2017-03-01');
INSERT INTO accounts (account_number, customer_id, account_type, balance, account_status, daily_transfer_limit, last_transaction_date, account_open_date) VALUES
('AC1000234571', 'CUST00003', 'SAVINGS_REGULAR', 800.00,    'DORMANT', 200000, DATE '2024-11-02', DATE '2012-09-15');
INSERT INTO accounts (account_number, customer_id, account_type, balance, account_status, daily_transfer_limit, last_transaction_date, account_open_date) VALUES
('AC1000234572', 'CUST00003', 'OVERDRAFT',       -75000.00, 'ACTIVE',  500000, DATE '2026-06-29', DATE '2013-04-11');
INSERT INTO accounts (account_number, customer_id, account_type, balance, account_status, daily_transfer_limit, last_transaction_date, account_open_date) VALUES
('AC1000234573', 'CUST00004', 'SAVINGS_ZERO_BAL',12000.00,  'ACTIVE',  100000, DATE '2026-06-27', DATE '2019-03-25');
INSERT INTO accounts (account_number, customer_id, account_type, balance, account_status, daily_transfer_limit, last_transaction_date, account_open_date) VALUES
('AC1000234574', 'CUST00005', 'CURRENT_PREMIUM', 18500.00,  'ACTIVE',  2000000,DATE '2026-06-30', DATE '2016-05-20');
INSERT INTO accounts (account_number, customer_id, account_type, balance, account_status, daily_transfer_limit, last_transaction_date, account_open_date) VALUES
('AC1000234575', 'CUST00006', 'SAVINGS_REGULAR', 6500000.00,'ACTIVE',  500000, DATE '2026-06-30', DATE '2018-12-01');
INSERT INTO accounts (account_number, customer_id, account_type, balance, account_status, daily_transfer_limit, last_transaction_date, account_open_date) VALUES
('AC1000234576', 'CUST00007', 'SAVINGS_PREMIUM', 95000.00,  'ACTIVE',  300000, DATE '2026-06-26', DATE '2010-01-20');
INSERT INTO accounts (account_number, customer_id, account_type, balance, account_status, daily_transfer_limit, last_transaction_date, account_open_date) VALUES
('AC1000234577', 'CUST00008', 'SAVINGS_REGULAR', 250.00,    'DORMANT', 100000, DATE '2024-05-14', DATE '2020-07-10');
INSERT INTO accounts (account_number, customer_id, account_type, balance, account_status, daily_transfer_limit, last_transaction_date, account_open_date) VALUES
('AC1000234578', 'CUST00002', 'SAVINGS_REGULAR', 15750.00,  'ACTIVE',  200000, DATE '2026-06-30', DATE '2021-08-09');

-----------------------------------------------------------------------------
-- TRANSACTION_LEDGER
-- Includes: a velocity burst (6 debits within 10 minutes) for AC1000234570,
-- a geo-mismatch + impossible-travel pair for AC1000234576, an amount
-- anomaly (10x average) for AC1000234569, a large first-time-beneficiary
-- transfer for AC1000234575, and an odd-hour high-value transaction for
-- AC1000234574 -- to validate the fraud scoring engine (#9).
-----------------------------------------------------------------------------
-- Normal history / statement data (#6)
INSERT INTO transaction_ledger (txn_id, account_number, txn_date, txn_type, txn_amount, running_balance, narration, origin_country) VALUES
(seq_txn_id.NEXTVAL, 'AC1000234567', DATE '2026-04-05', 'DEPOSIT',      20000, 25000,  'Cash deposit', 'IND');
INSERT INTO transaction_ledger (txn_id, account_number, txn_date, txn_type, txn_amount, running_balance, narration, origin_country) VALUES
(seq_txn_id.NEXTVAL, 'AC1000234567', DATE '2026-05-01', 'SALARY_CREDIT', 30000, 55000,  'Salary credit - Acme Corp', 'IND');
INSERT INTO transaction_ledger (txn_id, account_number, txn_date, txn_type, txn_amount, running_balance, narration, origin_country) VALUES
(seq_txn_id.NEXTVAL, 'AC1000234567', DATE '2026-05-15', 'WITHDRAWAL',    10000, 45000,  'ATM withdrawal', 'IND');
INSERT INTO transaction_ledger (txn_id, account_number, txn_date, txn_type, txn_amount, running_balance, narration, origin_country) VALUES
(seq_txn_id.NEXTVAL, 'AC1000234567', DATE '2026-06-25', 'FEE',           500,   44500, 'SMS alert charges', 'IND');

-- Velocity rule trigger: 6 outward txns within a 10-minute window
INSERT INTO transaction_ledger (txn_id, account_number, txn_date, txn_type, txn_amount, running_balance, narration, origin_country) VALUES
(seq_txn_id.NEXTVAL, 'AC1000234570', TIMESTAMP '2026-06-28 22:01:00', 'TRANSFER_OUT', 500, 2700, 'UPI transfer', 'IND');
INSERT INTO transaction_ledger (txn_id, account_number, txn_date, txn_type, txn_amount, running_balance, narration, origin_country) VALUES
(seq_txn_id.NEXTVAL, 'AC1000234570', TIMESTAMP '2026-06-28 22:02:30', 'TRANSFER_OUT', 500, 2200, 'UPI transfer', 'IND');
INSERT INTO transaction_ledger (txn_id, account_number, txn_date, txn_type, txn_amount, running_balance, narration, origin_country) VALUES
(seq_txn_id.NEXTVAL, 'AC1000234570', TIMESTAMP '2026-06-28 22:03:45', 'TRANSFER_OUT', 300, 1900, 'UPI transfer', 'IND');
INSERT INTO transaction_ledger (txn_id, account_number, txn_date, txn_type, txn_amount, running_balance, narration, origin_country) VALUES
(seq_txn_id.NEXTVAL, 'AC1000234570', TIMESTAMP '2026-06-28 22:04:50', 'TRANSFER_OUT', 300, 1600, 'UPI transfer', 'IND');
INSERT INTO transaction_ledger (txn_id, account_number, txn_date, txn_type, txn_amount, running_balance, narration, origin_country) VALUES
(seq_txn_id.NEXTVAL, 'AC1000234570', TIMESTAMP '2026-06-28 22:06:10', 'TRANSFER_OUT', 200, 1400, 'UPI transfer', 'IND');
INSERT INTO transaction_ledger (txn_id, account_number, txn_date, txn_type, txn_amount, running_balance, narration, origin_country) VALUES
(seq_txn_id.NEXTVAL, 'AC1000234570', TIMESTAMP '2026-06-28 22:07:55', 'TRANSFER_OUT', 200, 1200, 'UPI transfer', 'IND');

-- Geo-mismatch + impossible travel: registered country USA, txn from ARE then GBR 40 min later
INSERT INTO transaction_ledger (txn_id, account_number, txn_date, txn_type, txn_amount, running_balance, narration, origin_country) VALUES
(seq_txn_id.NEXTVAL, 'AC1000234576', TIMESTAMP '2026-06-29 09:00:00', 'WITHDRAWAL', 15000, 80000, 'ATM withdrawal - Dubai', 'ARE');
INSERT INTO transaction_ledger (txn_id, account_number, txn_date, txn_type, txn_amount, running_balance, narration, origin_country) VALUES
(seq_txn_id.NEXTVAL, 'AC1000234576', TIMESTAMP '2026-06-29 09:40:00', 'WITHDRAWAL', 12000, 68000, 'ATM withdrawal - London', 'GBR');

-- Amount anomaly: historical average is low (~2,000), this txn is 10x+ that
INSERT INTO transaction_ledger (txn_id, account_number, txn_date, txn_type, txn_amount, running_balance, narration, origin_country) VALUES
(seq_txn_id.NEXTVAL, 'AC1000234569', DATE '2026-04-10', 'WITHDRAWAL', 1800, 1248200, 'ATM withdrawal', 'IND');
INSERT INTO transaction_ledger (txn_id, account_number, txn_date, txn_type, txn_amount, running_balance, narration, origin_country) VALUES
(seq_txn_id.NEXTVAL, 'AC1000234569', DATE '2026-05-10', 'WITHDRAWAL', 2100, 1246100, 'ATM withdrawal', 'IND');
INSERT INTO transaction_ledger (txn_id, account_number, txn_date, txn_type, txn_amount, running_balance, narration, origin_country) VALUES
(seq_txn_id.NEXTVAL, 'AC1000234569', DATE '2026-06-10', 'WITHDRAWAL', 1900, 1244200, 'ATM withdrawal', 'IND');
INSERT INTO transaction_ledger (txn_id, account_number, txn_date, txn_type, txn_amount, running_balance, narration, origin_country) VALUES
(seq_txn_id.NEXTVAL, 'AC1000234569', DATE '2026-06-30', 'WITHDRAWAL', 25000, 1219200, 'Large cash withdrawal', 'IND');

-- Large first-time transfer to a new beneficiary
INSERT INTO transaction_ledger (txn_id, account_number, txn_date, txn_type, txn_amount, running_balance, narration, origin_country, beneficiary_id) VALUES
(seq_txn_id.NEXTVAL, 'AC1000234575', DATE '2026-06-29', 'TRANSFER_OUT', 250000, 6250000, 'Transfer to new beneficiary', 'IND', 'BENEF9001');

-- Odd-hour high-value transaction (2:15 AM)
INSERT INTO transaction_ledger (txn_id, account_number, txn_date, txn_type, txn_amount, running_balance, narration, origin_country) VALUES
(seq_txn_id.NEXTVAL, 'AC1000234574', TIMESTAMP '2026-06-30 02:15:00', 'TRANSFER_OUT', 45000, -26500, 'Online transfer', 'IND');

-----------------------------------------------------------------------------
-- LOAN_MASTER
-- Loan #1: standard fixed-rate home loan
-- Loan #2: floating-rate auto loan with a rate reset scheduled
-- Loan #3: restructured personal loan (tests SPECIAL_MENTION override, #10)
-- Loan #4: mortgage far past due (tests DOUBTFUL/LOSS bucket, #10)
-- Loan #5: education loan, current, low DPD
-----------------------------------------------------------------------------
INSERT INTO loan_master (loan_account_number, customer_id, loan_type, principal_amount, outstanding_principal, annual_interest_rate, tenure_months, disbursement_date, rate_reset_frequency_months, collateral_value, is_restructured, restructure_date, loan_status) VALUES
('LN5000011234', 'CUST00001', 'HOME_LOAN',     5000000, 4650000, 8.500, 240, DATE '2024-01-15', 0,  6000000, 'N', NULL, 'ACTIVE');
INSERT INTO loan_master (loan_account_number, customer_id, loan_type, principal_amount, outstanding_principal, annual_interest_rate, tenure_months, disbursement_date, rate_reset_frequency_months, collateral_value, is_restructured, restructure_date, loan_status) VALUES
('LN5000011235', 'CUST00002', 'AUTO_LOAN',      800000,  620000, 9.250,  60, DATE '2024-06-01', 12, 700000,  'N', NULL, 'ACTIVE');
INSERT INTO loan_master (loan_account_number, customer_id, loan_type, principal_amount, outstanding_principal, annual_interest_rate, tenure_months, disbursement_date, rate_reset_frequency_months, collateral_value, is_restructured, restructure_date, loan_status) VALUES
('LN5000011236', 'CUST00003', 'PERSONAL_LOAN',  300000,  260000, 13.500, 36, DATE '2025-09-01', 0,  0,       'Y', DATE '2026-02-15', 'ACTIVE');
INSERT INTO loan_master (loan_account_number, customer_id, loan_type, principal_amount, outstanding_principal, annual_interest_rate, tenure_months, disbursement_date, rate_reset_frequency_months, collateral_value, is_restructured, restructure_date, loan_status) VALUES
('LN5000011237', 'CUST00004', 'MORTGAGE',      2500000, 2350000, 7.750, 180, DATE '2020-03-10', 0,  1800000, 'N', NULL, 'ACTIVE');
INSERT INTO loan_master (loan_account_number, customer_id, loan_type, principal_amount, outstanding_principal, annual_interest_rate, tenure_months, disbursement_date, rate_reset_frequency_months, collateral_value, is_restructured, restructure_date, loan_status) VALUES
('LN5000011238', 'CUST00005', 'EDUCATION_LOAN', 600000,  580000, 6.900,  84, DATE '2025-08-20', 0,  0,       'N', NULL, 'ACTIVE');

-----------------------------------------------------------------------------
-- LOAN_RATE_RESET_HISTORY  (for the floating-rate auto loan, LN5000011235)
-----------------------------------------------------------------------------
INSERT INTO loan_rate_reset_history (loan_account_number, effective_installment_no, revised_annual_rate, reset_date) VALUES
('LN5000011235', 13, 9.750, DATE '2025-06-01');
INSERT INTO loan_rate_reset_history (loan_account_number, effective_installment_no, revised_annual_rate, reset_date) VALUES
('LN5000011235', 25, 9.500, DATE '2026-06-01');

-----------------------------------------------------------------------------
-- INTEREST_RATE_MASTER  (tiered rates by product/balance slab, used by #8)
-----------------------------------------------------------------------------
-- SAVINGS_REGULAR
INSERT INTO interest_rate_master (product_code, min_balance, max_balance, annual_rate, effective_date) VALUES
('SAVINGS_REGULAR', 0,        100000,   3.000, DATE '2026-01-01');
INSERT INTO interest_rate_master (product_code, min_balance, max_balance, annual_rate, effective_date) VALUES
('SAVINGS_REGULAR', 100000.01, 1000000, 3.500, DATE '2026-01-01');
INSERT INTO interest_rate_master (product_code, min_balance, max_balance, annual_rate, effective_date) VALUES
('SAVINGS_REGULAR', 1000000.01, NULL,   4.000, DATE '2026-01-01');
-- SAVINGS_PREMIUM
INSERT INTO interest_rate_master (product_code, min_balance, max_balance, annual_rate, effective_date) VALUES
('SAVINGS_PREMIUM', 0,        1000000,  3.750, DATE '2026-01-01');
INSERT INTO interest_rate_master (product_code, min_balance, max_balance, annual_rate, effective_date) VALUES
('SAVINGS_PREMIUM', 1000000.01, NULL,   4.250, DATE '2026-01-01');
-- SAVINGS_ZERO_BAL
INSERT INTO interest_rate_master (product_code, min_balance, max_balance, annual_rate, effective_date) VALUES
('SAVINGS_ZERO_BAL', 0,       NULL,     2.750, DATE '2026-01-01');
-- TERM_DEPOSIT
INSERT INTO interest_rate_master (product_code, min_balance, max_balance, annual_rate, effective_date) VALUES
('TERM_DEPOSIT', 0,           NULL,     6.500, DATE '2026-01-01');
-- OVERDRAFT (charged on utilized balance)
INSERT INTO interest_rate_master (product_code, min_balance, max_balance, annual_rate, effective_date) VALUES
('OVERDRAFT', 0,              NULL,     11.500, DATE '2026-01-01');

-----------------------------------------------------------------------------
-- HOLIDAY_CALENDAR
-----------------------------------------------------------------------------
INSERT INTO holiday_calendar (holiday_date, calendar_type, description) VALUES
(DATE '2026-01-26', 'NATIONAL', 'Republic Day');
INSERT INTO holiday_calendar (holiday_date, calendar_type, description) VALUES
(DATE '2026-08-15', 'NATIONAL', 'Independence Day');
INSERT INTO holiday_calendar (holiday_date, calendar_type, description) VALUES
(DATE '2026-10-02', 'NATIONAL', 'Gandhi Jayanti');

-----------------------------------------------------------------------------
-- LOAN_REPAYMENT_TRACKER  (DPD snapshot as of quarter-end 30-JUN-2026)
-- Deliberately spans every NPA bucket boundary tested by program #10:
--   LN5000011234 ->   0 DPD  -> STANDARD
--   LN5000011235 ->  45 DPD  -> SPECIAL_MENTION
--   LN5000011236 ->  20 DPD  -> STANDARD by DPD, but restructured within
--                                12 months -> overridden to SPECIAL_MENTION
--   LN5000011237 -> 400 DPD  -> DOUBTFUL
--   LN5000011238 -> 650 DPD  -> LOSS
-----------------------------------------------------------------------------
INSERT INTO loan_repayment_tracker (loan_account_number, as_of_date, days_past_due, last_payment_date, last_payment_amount) VALUES
('LN5000011234', DATE '2026-06-30', 0,   DATE '2026-06-05', 43500);
INSERT INTO loan_repayment_tracker (loan_account_number, as_of_date, days_past_due, last_payment_date, last_payment_amount) VALUES
('LN5000011235', DATE '2026-06-30', 45,  DATE '2026-05-10', 14200);
INSERT INTO loan_repayment_tracker (loan_account_number, as_of_date, days_past_due, last_payment_date, last_payment_amount) VALUES
('LN5000011236', DATE '2026-06-30', 20,  DATE '2026-06-01', 9800);
INSERT INTO loan_repayment_tracker (loan_account_number, as_of_date, days_past_due, last_payment_date, last_payment_amount) VALUES
('LN5000011237', DATE '2026-06-30', 400, DATE '2025-05-20', 22000);
INSERT INTO loan_repayment_tracker (loan_account_number, as_of_date, days_past_due, last_payment_date, last_payment_amount) VALUES
('LN5000011238', DATE '2026-06-30', 650, DATE '2024-09-15', 7500);

-----------------------------------------------------------------------------
-- NPA_CLASSIFICATION_HISTORY  (prior quarter, 31-MAR-2026, to test movement
-- reporting: LN5000011237 was SUBSTANDARD and should show as DOWNGRADED to
-- DOUBTFUL this quarter; LN5000011234 was STANDARD and stays UNCHANGED)
-----------------------------------------------------------------------------
INSERT INTO npa_classification_history (loan_account_number, classification_date, classification, days_past_due, outstanding_principal, collateral_cover_pct, provisioning_amount, prior_classification, movement_type) VALUES
('LN5000011234', DATE '2026-03-31', 'STANDARD',    0,   4700000, 127.66, 18800.00,  'STANDARD',    'UNCHANGED');
INSERT INTO npa_classification_history (loan_account_number, classification_date, classification, days_past_due, outstanding_principal, collateral_cover_pct, provisioning_amount, prior_classification, movement_type) VALUES
('LN5000011235', DATE '2026-03-31', 'STANDARD',    0,   680000,  102.94, 2720.00,   'STANDARD',    'UNCHANGED');
INSERT INTO npa_classification_history (loan_account_number, classification_date, classification, days_past_due, outstanding_principal, collateral_cover_pct, provisioning_amount, prior_classification, movement_type) VALUES
('LN5000011237', DATE '2026-03-31', 'SUBSTANDARD', 120, 2400000, 76.60,  456000.00, 'SPECIAL_MENTION', 'DOWNGRADED');
INSERT INTO npa_classification_history (loan_account_number, classification_date, classification, days_past_due, outstanding_principal, collateral_cover_pct, provisioning_amount, prior_classification, movement_type) VALUES
('LN5000011238', DATE '2026-03-31', 'DOUBTFUL',    560, 590000,  0.00,   590000.00, 'DOUBTFUL',    'UNCHANGED');

COMMIT;

-----------------------------------------------------------------------------
-- Quick sanity checks (optional -- run manually)
-----------------------------------------------------------------------------
-- SELECT account_number, account_type, balance, account_status FROM accounts ORDER BY 1;
-- SELECT loan_account_number, loan_type, outstanding_principal, is_restructured FROM loan_master ORDER BY 1;
-- SELECT COUNT(*) FROM transaction_ledger;
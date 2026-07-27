/*==============================================================================
  Program   : 01_simple_calculate_simple_interest.sql
  Category  : SIMPLE
  Purpose   : Calculate simple interest for a fixed deposit or short-term loan.
  Pattern   : Single function, IF/ELSE branching, no loops, no cursors.
==============================================================================*/

CREATE OR REPLACE FUNCTION fn_calculate_simple_interest (
    p_principal      IN  NUMBER,
    p_annual_rate    IN  NUMBER,   -- e.g. 7.5 means 7.5%
    p_tenure_days    IN  NUMBER,
    p_day_count_basis IN VARCHAR2 DEFAULT '365'  -- '360' or '365'
) RETURN NUMBER
IS
    v_interest       NUMBER(18,2);
    v_basis_days     NUMBER;
BEGIN
    -- Basic input validation
    IF p_principal IS NULL OR p_principal <= 0 THEN
        RAISE_APPLICATION_ERROR(-20001, 'Principal amount must be greater than zero.');
    END IF;

    IF p_annual_rate IS NULL OR p_annual_rate < 0 THEN
        RAISE_APPLICATION_ERROR(-20002, 'Interest rate cannot be negative.');
    END IF;

    IF p_tenure_days IS NULL OR p_tenure_days <= 0 THEN
        RAISE_APPLICATION_ERROR(-20003, 'Tenure in days must be greater than zero.');
    END IF;

    -- Determine day count basis
    IF p_day_count_basis = '360' THEN
        v_basis_days := 360;
    ELSE
        v_basis_days := 365;
    END IF;

    -- Simple Interest = P * R * T / (100 * basis_days)
    v_interest := ROUND( (p_principal * p_annual_rate * p_tenure_days) /
                          (100 * v_basis_days), 2 );

    RETURN v_interest;

EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error in fn_calculate_simple_interest: ' || SQLERRM);
        RAISE;
END fn_calculate_simple_interest;
/

-- Sample usage:
-- SELECT fn_calculate_simple_interest(100000, 7.5, 180, '365') AS interest_amount FROM dual;
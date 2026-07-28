/*==============================================================================
  Fixture: campbell_example.sql
  Purpose : PL/SQL transliteration of the worked example on page 9 of
            G. Ann Campbell, "Cognitive Complexity - a new way of measuring
            understandability" (SonarSource v1.7, 2023).

  The original Java in the whitepaper:

      void myMethod () {
        try {
          if (condition1) {                   // +1
            for (int i = 0; i < 10; i++) {    // +2 (nesting=1)
              while (condition2) { ... }      // +3 (nesting=2)
            }
          }
        } catch (ExcepType1 | ExcepType2 e) { // +1
          if (condition2) { ... }             // +2 (nesting=1)
        }
      }                                       // Cognitive Complexity 9

  Expected Cognitive Complexity: 9
    - the enclosing block (try) gets NO increment and does NOT raise nesting
    - EXCEPTION WHEN maps to catch: +1, and raises nesting for its children
    - the IF inside the handler is at nesting 1: +1 structural +1 nesting = +2

  This is the single most important test in the suite: it validates our
  implementation against the metric author's own published arithmetic
  rather than against our own expectations.
==============================================================================*/

CREATE OR REPLACE PROCEDURE sp_campbell_example (
    p_flag_one  IN  VARCHAR2,
    p_flag_two  IN  VARCHAR2,
    p_result    OUT NUMBER
)
IS
    v_total  NUMBER := 0;
    v_i      NUMBER;
BEGIN
    BEGIN                                       -- try: +0, nesting unchanged
        IF p_flag_one = 'Y' THEN                -- +1 (nesting 0)
            FOR v_i IN 1 .. 10 LOOP             -- +2 (nesting 1)
                WHILE p_flag_two = 'Y' LOOP     -- +3 (nesting 2)
                    v_total := v_total + 1;
                    EXIT;
                END LOOP;
            END LOOP;
        END IF;
    EXCEPTION
        WHEN VALUE_ERROR THEN                   -- +1 (catch, nesting 0)
            IF p_flag_two = 'Y' THEN            -- +2 (nesting 1)
                v_total := -1;
            END IF;
    END;

    p_result := v_total;
END sp_campbell_example;
/

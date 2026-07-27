SET DEFINE OFF
SET SERVEROUTPUT ON
PROMPT Deploying schema and account management package...
@01_schema.sql
@02_account_mgmt.sql
@03_seed.sql
@04_reporting.sql
PROMPT Done.

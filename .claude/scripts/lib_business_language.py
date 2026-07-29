#!/usr/bin/env python3
"""
Business language layer — turns machine identifiers into words people read.

WHY THIS EXISTS
---------------
Every upstream agent speaks in identifiers because identifiers are stable and
joinable: `PROC-.SP_TRANSFER_FUNDS`, `ACCOUNTS.LAST_TXN_DATE`, `p_from_acct`.
That is correct for artifacts and wrong for a document. A sponsor reading
"PROC-.SP_TRANSFER_FUNDS is a procedure classified as SINGLE_RECORD_TRANSACTION"
learns nothing; a reader who sees "Transfer Funds Between Accounts — handles one
transfer at a time" learns what the system does.

This module is the single place that translation happens, so the vocabulary is
consistent across every chapter and can be corrected in one edit.

The machine identifier is never destroyed — it is carried alongside in a
`Term`, so the same sentence can serve a business reader and a build team, and
so a machine consumer can always recover the join key.
"""

import re

# Expansions are ordered longest-first at match time so DT does not eat DTL.
# Sourced from the identifiers actually present in this corpus plus the common
# Oracle/banking shorthand a PL/SQL codebase of this era uses.
ABBREVIATIONS = {
    "ACCT": "Account", "ACCTS": "Accounts", "AC": "Account",
    "TXN": "Transaction", "TXNS": "Transactions", "TRANS": "Transaction",
    "AMT": "Amount", "BAL": "Balance", "CUST": "Customer", "CUSTS": "Customers",
    # "NO" is deliberately NOT mapped to "Number": it is an ordinary English
    # word, and expanding it turned "no preceding condition matched" into
    # "Number Preceding Condition Matched".
    "STAT": "Status", "STS": "Status", "NUM": "Number", "NBR": "Number",
    "DT": "Date", "TS": "Timestamp", "PMT": "Payment", "PMTS": "Payments",
    "INT": "Interest", "PRIN": "Principal", "LMT": "Limit", "MIN": "Minimum",
    "MAX": "Maximum", "AVG": "Average", "IND": "Indicator", "FLG": "Flag",
    "FLAG": "Indicator", "ERR": "Error", "MSG": "Message", "DESC": "Description",
    "REF": "Reference", "SEQ": "Sequence", "CALC": "Calculated", "PCT": "Percentage",
    "QTY": "Quantity", "ADDR": "Address", "TEL": "Telephone", "ID": "Identifier",
    "NPA": "Non-Performing Asset", "EMI": "Equated Monthly Instalment",
    "GL": "General Ledger", "KYC": "Know Your Customer", "IFSC": "Bank Branch Code",
    "DR": "Debit", "CR": "Credit", "OD": "Overdraft", "FD": "Fixed Deposit",
    "RD": "Recurring Deposit", "SB": "Savings Bank", "CA": "Current Account",
}

# Prefixes carrying no business meaning — Oracle naming convention noise.
_OBJECT_PREFIXES = ("SP_", "PROC_", "FN_", "FUNC_", "PKG_", "TRG_", "TRIG_", "USP_")
# `e_` is the Oracle convention for a user-defined exception, so stripping it
# turns e_insufficient_balance into "Insufficient Balance" rather than the
# meaningless "E Insufficient Balance".
_VARIABLE_PREFIXES = ("P_", "V_", "L_", "G_", "C_", "R_", "I_", "O_", "E_")

# Small words that stay lowercase inside a title.
_MINOR_WORDS = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "into",
                "of", "on", "or", "the", "to", "with", "per", "vs"}


def _expand_token(token: str) -> str:
    upper = token.upper()
    if upper in ABBREVIATIONS:
        return ABBREVIATIONS[upper]
    if upper.isdigit():
        return token
    return token.capitalize()


def _titlecase(words: list) -> str:
    out = []
    for i, w in enumerate(words):
        if i > 0 and w.lower() in _MINOR_WORDS:
            out.append(w.lower())
        else:
            out.append(w)
    return " ".join(out)


def humanise(identifier: str, strip_variable_prefix: bool = True) -> str:
    """
    `p_from_account` -> "From Account"; `LAST_TXN_DATE` -> "Last Transaction Date".

    Dotted access keeps only the final part: `rec.balance` -> "Balance". The
    record variable is a loop artefact with no business meaning, and "Rec
    Balance" is worse than saying nothing.
    """
    if not identifier:
        return ""
    ident = str(identifier).split(".")[-1].strip()
    if strip_variable_prefix:
        for p in _VARIABLE_PREFIXES:
            if ident.upper().startswith(p) and len(ident) > len(p):
                ident = ident[len(p):]
                break
    parts = [p for p in re.split(r"[_\s]+", ident) if p]
    if not parts:
        return identifier
    return _titlecase([_expand_token(p) for p in parts])


def object_title(object_id: str) -> str:
    """
    `PROC-.SP_TRANSFER_FUNDS` -> "Transfer Funds".
    `PKGB-APP.ACCOUNT_MGMT::CREDIT_ACCOUNT` -> "Account Mgmt: Credit Account".

    The type prefix and owner qualifier are structural bookkeeping; the reader
    wants the capability name.
    """
    if not object_id:
        return ""
    name = object_id.split("-.", 1)[-1] if "-." in object_id else object_id
    if "-" in name and "." in name.split("-", 1)[0]:
        name = name.split(".", 1)[-1]
    if "::" in name:
        pkg, member = name.split("::", 1)
        return f"{humanise(pkg, False)}: {humanise(_strip_object_prefix(member), False)}"
    return humanise(_strip_object_prefix(name), False)


def _strip_object_prefix(name: str) -> str:
    upper = name.upper()
    for p in _OBJECT_PREFIXES:
        if upper.startswith(p) and len(name) > len(p):
            return name[len(p):]
    return name


def entity_title(table_name: str) -> str:
    """`TRANSACTION_LEDGER` -> "Transaction Ledger"."""
    return humanise(table_name, strip_variable_prefix=False)


def object_kind_phrase(obj_type: str) -> str:
    return {"PROCEDURE": "business process", "FUNCTION": "calculation",
            "PACKAGE": "grouped set of processes", "PACKAGE_BODY": "grouped set of processes",
            "TRIGGER": "automatic reaction"}.get((obj_type or "").upper(), "program")


SHAPE_PHRASES = {
    "BATCH_PROCESSOR": ("Batch process",
                        "Works through many records in one run, one at a time."),
    "SINGLE_RECORD_TRANSACTION": ("Single transaction",
                                  "Handles one business event from start to finish."),
    "CALCULATION": ("Calculation",
                    "Takes values in, returns a computed result, changes no data."),
    "QUERY_ONLY": ("Enquiry",
                   "Reads information and reports it back without changing anything."),
    "VALIDATOR": ("Validation",
                  "Checks whether something is allowed and reports the verdict."),
}


def shape_phrase(shape: str) -> tuple:
    return SHAPE_PHRASES.get((shape or "").upper(),
                             ("Program", "Performs processing described below."))


def anchor(heading: str) -> str:
    """GitHub-flavoured markdown anchor for a heading, for the clickable TOC."""
    a = heading.strip().lower()
    a = re.sub(r"[^\w\s-]", "", a)
    return re.sub(r"[\s_]+", "-", a).strip("-")


def sentence_case(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    return text[0].upper() + text[1:]


_OPERATOR_WORDS = [
    (">=", "is at or above"), ("<=", "is at or below"), ("<>", "is not"),
    ("!=", "is not"), ("^=", "is not"), ("=", "is"), ("<", "is below"), (">", "is above"),
]
_IDENTIFIER_RE = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_$#]*(?:\.[a-zA-Z_][a-zA-Z0-9_$#]*)?)\b")
_SQL_WORDS = {
    "AND", "OR", "NOT", "IS", "NULL", "IN", "LIKE", "BETWEEN", "EXISTS", "SELECT",
    "FROM", "WHERE", "THEN", "ELSE", "END", "CASE", "WHEN", "TRUE", "FALSE",
    "NVL", "ROUND", "TRUNC", "SUM", "COUNT", "AVG", "MAX", "MIN", "EXTRACT",
    "LAST_DAY", "SYSDATE", "DAY", "MONTH", "YEAR", "LEAST", "GREATEST", "ABS",
}


def humanise_condition(text: str) -> str:
    """
    `v_from_balance < p_amount` -> "From Balance is below Amount".

    A business reader cannot parse a source expression, and a specification
    that only a developer can check is not reviewable. The exact expression is
    always kept alongside in a code span, so precision is not lost — this is
    the readable half of a dual presentation, not a replacement.
    """
    if not text:
        return ""
    out = str(text).strip()

    # Protect quoted literals from identifier substitution.
    literals = []

    def _stash(m):
        literals.append(m.group(0))
        return f"\x00{len(literals) - 1}\x00"

    out = re.sub(r"'[^']*'", _stash, out)

    # Identifiers are substituted BEFORE operators. Doing it the other way
    # round feeds the inserted words ("is below") back through the identifier
    # pass, which title-cases them into "is Below".
    def _sub_ident(m):
        token = m.group(1)
        if token.upper() in _SQL_WORDS or token.replace(".", "").isdigit():
            return token
        return humanise(token)

    out = _IDENTIFIER_RE.sub(_sub_ident, out)

    for op, word in _OPERATOR_WORDS:
        out = out.replace(op, f" {word} ")
    out = re.sub(r"\bIS\s+NOT\s+NULL\b", "is present", out, flags=re.IGNORECASE)
    out = re.sub(r"\bIS\s+NULL\b", "is missing", out, flags=re.IGNORECASE)
    out = re.sub(r"\bAND\b", "and", out).replace(" OR ", " or ")

    for i, lit in enumerate(literals):
        out = out.replace(f"\x00{i}\x00", lit)
    return re.sub(r"\s{2,}", " ", out).strip()


def humanise_identifiers(text: str) -> str:
    """
    Replace only things that are unmistakably code identifiers, leaving
    ordinary words alone.

    Used for outcome phrases such as "set New Balance to rec.balance +
    v_interest_amount and update accounts", which are already mostly English.
    Running the full condition translator over them would title-case the
    ordinary words too ("Set ... To ... And Update").
    """
    if not text:
        return ""

    def _sub(m):
        token = m.group(0)
        if token.upper() in _SQL_WORDS:
            return token
        return humanise(token)

    # Only tokens containing an underscore or a dot — i.e. clearly identifiers.
    return re.sub(r"\b[A-Za-z][A-Za-z0-9$#]*(?:[_.][A-Za-z0-9_$#]+)+\b", _sub, text)


def plain_type(oracle_type: str, normalized: str = "") -> str:
    """`NUMBER(18,2)` -> "Decimal number (18 digits, 2 decimal places)"."""
    t = (oracle_type or "").upper()
    m = re.match(r"NUMBER\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)", t)
    if m:
        return f"Decimal number ({m.group(1)} digits, {m.group(2)} decimal places)"
    m = re.match(r"NUMBER\s*\(\s*(\d+)\s*\)", t)
    if m:
        return f"Whole number (up to {m.group(1)} digits)"
    if t.startswith("NUMBER"):
        return "Number"
    m = re.match(r"(?:VAR)?CHAR2?\s*\(\s*(\d+)", t)
    if m:
        return f"Text (up to {m.group(1)} characters)"
    if t.startswith("DATE"):
        return "Date"
    if t.startswith("TIMESTAMP"):
        return "Date and time"
    if t.startswith("CLOB") or t.startswith("BLOB"):
        return "Large object"
    return (normalized or oracle_type or "Unspecified").title()

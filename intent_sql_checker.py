"""
intent_sql_checker.py

Schema-independent consistency checking between:

    Natural-language intent
            +
          SQL

The checker does NOT execute SQL.

Detected mismatches:

    OPERATION_MISMATCH
    TARGET_MISMATCH
    FIELD_MISMATCH
    VALUE_MISMATCH
    SCOPE_MISMATCH

The implementation is intentionally schema-independent.
No employee/customer/product-specific rules are used.
"""

import re


# ============================================================
# Normalization helpers
# ============================================================

def _normalize_operation(operation):

    if operation is None:
        return "UNKNOWN"

    operation = str(operation).strip().upper()

    aliases = {
        "READ": "SELECT",
        "QUERY": "SELECT",
        "SEARCH": "SELECT",
        "RETRIEVE": "SELECT",

        "CREATE": "INSERT",
        "ADD": "INSERT",

        "MODIFY": "UPDATE",
        "CHANGE": "UPDATE",

        "REMOVE": "DELETE",
    }

    return aliases.get(
        operation,
        operation
    )


def _normalize_scope(scope):

    if scope is None:
        return "UNKNOWN"

    value = str(scope).strip().lower()

    aliases = {
        "zero": "ZERO_ROWS",
        "zero rows": "ZERO_ROWS",

        "one": "ONE_ROW",
        "one row": "ONE_ROW",
        "single": "ONE_ROW",
        "single row": "ONE_ROW",

        "multiple": "MULTIPLE_ROWS",
        "multiple rows": "MULTIPLE_ROWS",
        "many": "MULTIPLE_ROWS",

        "all": "ALL_ROWS",
        "all rows": "ALL_ROWS",

        "unknown": "UNKNOWN",
    }

    return aliases.get(
        value,
        value.upper().replace(" ", "_")
    )


def _normalize_identifier(value):

    if value is None:
        return ""

    value = str(value).strip()

    # Remove SQL identifier quoting.
    if len(value) >= 2:

        if (
            (value[0] == '"' and value[-1] == '"')
            or
            (value[0] == "`" and value[-1] == "`")
            or
            (value[0] == "[" and value[-1] == "]")
        ):

            value = value[1:-1]

    value = value.strip().lower()

    # --------------------------------------------------------
    # Handle qualified identifiers.
    #
    # Examples:
    #
    # e.salary
    # employees.salary
    # customers.balance
    #
    # All represent the same final column identifier.
    # --------------------------------------------------------

    if "." in value:

        value = value.split(".")[-1]

        value = value.strip()

        if len(value) >= 2:

            if (
                (value[0] == '"' and value[-1] == '"')
                or
                (value[0] == "`" and value[-1] == "`")
                or
                (value[0] == "[" and value[-1] == "]")
            ):

                value = value[1:-1]

    return value.strip()


def _normalize_sql_value(value):

    if value is None:
        return ""

    value = str(value).strip()

    value = value.rstrip(";").strip()

    # Remove surrounding SQL string quotes.
    if len(value) >= 2:

        if (
            (value[0] == "'" and value[-1] == "'")
            or
            (value[0] == '"' and value[-1] == '"')
        ):

            value = value[1:-1]

    return value.strip().lower()


def _is_unknown(value):

    if value is None:
        return True

    normalized = str(value).strip().lower()

    return normalized in {
        "",
        "unknown",
        "none",
        "null",
        "n/a",
        "na",
        "?",
    }


# ============================================================
# Target helpers
# ============================================================

def _is_all_target(value):

    if _is_unknown(value):
        return False

    normalized = str(value).strip().lower()

    explicit = {
        "all",
        "all rows",
        "all records",
        "every row",
        "every record",
        "entire table",
        "whole table",
    }

    if normalized in explicit:
        return True

    # Generic:
    #
    # all <entity>
    # every <entity>
    #

    if re.fullmatch(
        r"(all|every)\s+[a-z0-9_ -]+",
        normalized
    ):

        return True

    return False


# ============================================================
# SQL extraction helpers
# ============================================================

def _extract_where(sql):

    if not sql:
        return ""

    text = str(sql)

    lower = text.lower()

    in_single = False
    in_double = False
    in_backtick = False
    in_bracket = False

    where_start = -1
    i = 0

    while i < len(text):

        char = text[i]

        if (
            char == "'"
            and not in_double
            and not in_backtick
            and not in_bracket
        ):

            if (
                i + 1 < len(text)
                and text[i + 1] == "'"
            ):

                i += 2
                continue

            in_single = not in_single

        elif (
            char == '"'
            and not in_single
            and not in_backtick
            and not in_bracket
        ):

            in_double = not in_double

        elif (
            char == "`"
            and not in_single
            and not in_double
            and not in_bracket
        ):

            in_backtick = not in_backtick

        elif (
            char == "["
            and not in_single
            and not in_double
            and not in_backtick
        ):

            in_bracket = True

        elif char == "]" and in_bracket:

            in_bracket = False

        if not (
            in_single
            or in_double
            or in_backtick
            or in_bracket
        ):

            if where_start == -1:

                if lower.startswith(
                    "where",
                    i
                ):

                    before_ok = (
                        i == 0
                        or not (
                            lower[i - 1].isalnum()
                            or lower[i - 1] == "_"
                        )
                    )

                    after_index = i + 5

                    after_ok = (
                        after_index >= len(lower)
                        or not (
                            lower[after_index].isalnum()
                            or lower[after_index] == "_"
                        )
                    )

                    if before_ok and after_ok:

                        where_start = after_index
                        i = after_index
                        continue

            else:

                # Inside WHERE clause: stop at semicolon or trailing clauses
                if char == ";":
                    return text[where_start:i].strip()

                for kw in ("order by", "group by", "limit", "having"):
                    if lower.startswith(kw, i):
                        b_ok = (i == 0 or not (lower[i - 1].isalnum() or lower[i - 1] == "_"))
                        a_idx = i + len(kw)
                        a_ok = (a_idx >= len(lower) or not (lower[a_idx].isalnum() or lower[a_idx] == "_"))
                        if b_ok and a_ok:
                            return text[where_start:i].strip()

        i += 1

    if where_start != -1:
        res = text[where_start:].strip()
        return res.rstrip(";").strip()

    return ""


def _clean_predicate_part(part):
    """
    Clean a predicate expression by trimming whitespace, trailing semicolons,
    and balanced surrounding parentheses.
    Example: "(name = 'Anu');" -> "name = 'Anu'"
    """
    if not part:
        return ""
    part = part.strip().rstrip(";").strip()
    while part.startswith("(") and part.endswith(")"):
        depth = 0
        matched = True
        for idx, ch in enumerate(part):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and idx < len(part) - 1:
                    matched = False
                    break
        if matched and depth == 0:
            part = part[1:-1].strip()
        else:
            break
    return part


def _split_predicates(where_clause):

    if not where_clause:
        return []

    parts = []

    start = 0
    i = 0
    depth = 0

    in_single = False
    in_double = False
    in_backtick = False
    in_bracket = False

    text = where_clause

    while i < len(text):

        char = text[i]

        if (
            char == "'"
            and not in_double
            and not in_backtick
            and not in_bracket
        ):

            if (
                i + 1 < len(text)
                and text[i + 1] == "'"
            ):

                i += 2
                continue

            in_single = not in_single

        elif (
            char == '"'
            and not in_single
            and not in_backtick
            and not in_bracket
        ):

            in_double = not in_double

        elif (
            char == "`"
            and not in_single
            and not in_double
            and not in_bracket
        ):

            in_backtick = not in_backtick

        elif (
            char == "["
            and not in_single
            and not in_double
            and not in_backtick
        ):

            in_bracket = True

        elif char == "]" and in_bracket:

            in_bracket = False

        elif char == "(" and not in_single and not in_double and not in_backtick and not in_bracket:
            depth += 1

        elif char == ")" and not in_single and not in_double and not in_backtick and not in_bracket:
            if depth > 0:
                depth -= 1

        if not (
            in_single
            or in_double
            or in_backtick
            or in_bracket
        ) and depth == 0:

            # Split on AND or OR at the top level
            for keyword, klen in (("and", 3), ("or", 2)):

                if text[i:i + klen].lower() == keyword:

                    before_ok = (
                        i == 0
                        or not (
                            text[i - 1].isalnum()
                            or text[i - 1] == "_"
                        )
                    )

                    after_index = i + klen

                    after_ok = (
                        after_index >= len(text)
                        or not (
                            text[after_index].isalnum()
                            or text[after_index] == "_"
                        )
                    )

                    if before_ok and after_ok:

                        part = text[start:i].strip()
                        if part:
                            parts.append(part)

                        start = after_index
                        i = after_index
                        break

                    # Only check AND; if "and" matched but bounds not ok,
                    # don't try "or" for this position.
                    break

        i += 1

    final_part = text[
        start:
    ].strip()

    if final_part:

        parts.append(
            final_part
        )

    return parts


def _extract_predicates(sql):

    where_clause = _extract_where(
        sql
    )

    if not where_clause:
        return []

    predicates = []

    parts = _split_predicates(
        where_clause
    )

    # -----------------------------------------------------------
    # Patterns tried in order, from most-specific to least.
    # Each captures at minimum a "field" group.
    # -----------------------------------------------------------

    # 1. IS NOT NULL / IS NULL
    pat_is_null = re.compile(
        r"""^\s*
        (?P<field>
            "(?:[^"]|"")+" |
            `(?:[^`]|``)+` |
            \[(?:[^\]])+\] |
            [A-Za-z_][A-Za-z0-9_.]*
        )
        \s+IS\s+(?P<notnull>NOT\s+)?NULL\s*$""",
        re.IGNORECASE | re.VERBOSE,
    )

    # 2. BETWEEN x AND y
    pat_between = re.compile(
        r"""^\s*
        (?P<field>
            "(?:[^"]|"")+" |
            `(?:[^`]|``)+` |
            \[(?:[^\]])+\] |
            [A-Za-z_][A-Za-z0-9_.]*
        )
        \s+(?P<op>NOT\s+)?BETWEEN\s+
        (?P<lo>.+?)\s+AND\s+(?P<hi>.+)\s*$""",
        re.IGNORECASE | re.VERBOSE,
    )

    # 3. IN (...)
    pat_in = re.compile(
        r"""^\s*
        (?P<field>
            "(?:[^"]|"")+" |
            `(?:[^`]|``)+` |
            \[(?:[^\]])+\] |
            [A-Za-z_][A-Za-z0-9_.]*
        )
        \s+(?P<op>NOT\s+)?IN\s*\((?P<values>[^)]*)\)\s*$""",
        re.IGNORECASE | re.VERBOSE,
    )

    # 4. LIKE / NOT LIKE
    pat_like = re.compile(
        r"""^\s*
        (?P<field>
            "(?:[^"]|"")+" |
            `(?:[^`]|``)+` |
            \[(?:[^\]])+\] |
            [A-Za-z_][A-Za-z0-9_.]*
        )
        \s+(?P<op>NOT\s+)?LIKE\s+
        (?P<value>'(?:''|[^'])*'|"(?:""|[^"])*"|\S+)\s*$""",
        re.IGNORECASE | re.VERBOSE,
    )

    # 5. Simple comparison:  field op value
    pat_compare = re.compile(
        r"""^\s*
        (?P<field>
            "(?:[^"]|"")+" |
            `(?:[^`]|``)+` |
            \[(?:[^\]])+\] |
            [A-Za-z_][A-Za-z0-9_.]*
        )
        \s*
        (?P<operator>
            =   |
            !=  |
            <>  |
            <=  |
            >=  |
            <   |
            >
        )
        \s*
        (?P<value>
            '(?:''|[^'])*' |
            "(?:""|[^"])*" |
            [^,\s]+
        )
        \s*$""",
        re.IGNORECASE | re.VERBOSE,
    )

    for raw_part in parts:

        part = _clean_predicate_part(raw_part)

        if not part:
            continue

        # --- IS NULL / IS NOT NULL ---
        m = pat_is_null.match(part)
        if m:
            op = "IS NOT NULL" if m.group("notnull") else "IS NULL"
            predicates.append({
                "field": _normalize_identifier(m.group("field")),
                "operator": op,
                "value": "",
            })
            continue

        # --- BETWEEN ---
        m = pat_between.match(part)
        if m:
            op = "NOT BETWEEN" if m.group("op") else "BETWEEN"
            predicates.append({
                "field": _normalize_identifier(m.group("field")),
                "operator": op,
                "value": _normalize_sql_value(m.group("lo")),
            })
            continue

        # --- IN / NOT IN ---
        m = pat_in.match(part)
        if m:
            op = "NOT IN" if m.group("op") else "IN"
            raw_vals = m.group("values")
            vals = [
                _normalize_sql_value(v.strip())
                for v in raw_vals.split(",")
                if v.strip()
            ]
            first_val = vals[0] if vals else ""
            predicates.append({
                "field": _normalize_identifier(m.group("field")),
                "operator": op,
                "value": first_val,
                "values": vals,
            })
            continue

        # --- LIKE / NOT LIKE ---
        m = pat_like.match(part)
        if m:
            op = "NOT LIKE" if m.group("op") else "LIKE"
            predicates.append({
                "field": _normalize_identifier(m.group("field")),
                "operator": op,
                "value": _normalize_sql_value(m.group("value")),
            })
            continue

        # --- simple comparison ---
        m = pat_compare.match(part)
        if m:
            predicates.append({
                "field": _normalize_identifier(m.group("field")),
                "operator": m.group("operator"),
                "value": _normalize_sql_value(m.group("value")),
            })
            continue

        # --- unrecognised predicate: still capture the field name ---
        # Use the leading identifier as the field so field-presence
        # checks still work even for exotic expressions.
        lead = re.match(
            r"^\s*([A-Za-z_][A-Za-z0-9_.]*)",
            part
        )
        if lead:
            predicates.append({
                "field": _normalize_identifier(lead.group(1)),
                "operator": "UNKNOWN",
                "value": "",
            })

    return predicates


def _extract_select_fields(sql):

    if not sql:
        return []

    match = re.search(
        r"\bselect\b(.*?)\bfrom\b",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not match:
        return []

    field_text = match.group(
        1
    ).strip()

    if field_text == "*":
        return ["*"]

    fields = []

    current = []
    depth = 0

    for char in field_text:

        if char == "(":
            depth += 1

        elif char == ")":
            depth = max(
                0,
                depth - 1
            )

        if (
            char == ","
            and depth == 0
        ):

            field = "".join(
                current
            ).strip()

            if field:

                fields.append(
                    _normalize_identifier(
                        field
                    )
                )

            current = []

        else:

            current.append(
                char
            )

    final_field = "".join(
        current
    ).strip()

    if final_field:

        fields.append(
            _normalize_identifier(
                final_field
            )
        )

    return fields


def _extract_update_assignments(sql):

    if not sql:
        return []

    match = re.search(
        r"\bupdate\b.*?\bset\b"
        r"(.*?)(?:\bwhere\b|$)",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not match:
        return []

    assignment_text = match.group(
        1
    ).strip()

    assignments = []

    current = []
    depth = 0

    in_single = False
    in_double = False
    in_backtick = False

    parts = []

    for char in assignment_text:

        if (
            char == "'"
            and not in_double
            and not in_backtick
        ):

            in_single = not in_single

        elif (
            char == '"'
            and not in_single
            and not in_backtick
        ):

            in_double = not in_double

        elif (
            char == "`"
            and not in_single
            and not in_double
        ):

            in_backtick = not in_backtick

        elif (
            not in_single
            and not in_double
            and not in_backtick
        ):

            if char == "(":
                depth += 1

            elif char == ")":

                depth = max(
                    0,
                    depth - 1
                )

        if (
            char == ","
            and depth == 0
            and not in_single
            and not in_double
            and not in_backtick
        ):

            parts.append(
                "".join(
                    current
                ).strip()
            )

            current = []

        else:

            current.append(
                char
            )

    final_part = "".join(
        current
    ).strip()

    if final_part:

        parts.append(
            final_part
        )

    for part in parts:

        match = re.match(
            r"""
            ^\s*
            (?P<field>
                "(?:[^"]|"")+" |
                `(?:[^`]|``)+` |
                \[(?:[^\]])+\] |
                [A-Za-z_][A-Za-z0-9_.]*
            )
            \s*=\s*
            (?P<value>.*?)
            \s*$
            """,
            part,
            flags=re.IGNORECASE
            | re.VERBOSE
            | re.DOTALL,
        )

        if not match:
            continue

        assignments.append(
            {
                "field":
                    _normalize_identifier(
                        match.group("field")
                    ),

                "value":
                    match.group("value").strip(),
            }
        )

    return assignments


def _extract_insert_assignments(sql):

    if not sql:
        return []

    column_match = re.search(
        r"\binsert\s+into\b.*?"
        r"\((.*?)\)"
        r"\s*values\s*\(",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not column_match:
        return []

    columns_text = (
        column_match.group(1)
    )

    value_start = (
        column_match.end()
    )

    depth = 1
    i = value_start

    in_single = False
    in_double = False

    while (
        i < len(sql)
        and depth > 0
    ):

        char = sql[i]

        if (
            char == "'"
            and not in_double
        ):

            if (
                i + 1 < len(sql)
                and sql[i + 1] == "'"
            ):

                i += 2
                continue

            in_single = not in_single

        elif (
            char == '"'
            and not in_single
        ):

            in_double = not in_double

        elif (
            not in_single
            and not in_double
        ):

            if char == "(":
                depth += 1

            elif char == ")":
                depth -= 1

        i += 1

    values_text = sql[
        value_start:i - 1
    ]

    columns = [
        _normalize_identifier(
            column.strip()
        )
        for column
        in columns_text.split(",")
    ]

    values = []

    current = []

    in_single = False
    in_double = False

    depth = 0

    for char in values_text:

        if (
            char == "'"
            and not in_double
        ):

            in_single = not in_single

        elif (
            char == '"'
            and not in_single
        ):

            in_double = not in_double

        if (
            char == ","
            and not in_single
            and not in_double
            and depth == 0
        ):

            values.append(
                "".join(
                    current
                ).strip()
            )

            current = []

        else:

            current.append(
                char
            )

    final_value = "".join(
        current
    ).strip()

    if final_value:

        values.append(
            final_value
        )

    assignments = []

    for column, value in zip(
        columns,
        values
    ):

        assignments.append(
            {
                "field": column,
                "value": value,
            }
        )

    return assignments


# ============================================================
# Target checking
# ============================================================

def _check_filter_target(
    operation,
    intent,
    sql,
    mismatches,
):

    requested_target = (
        intent.get("target")
    )

    if _is_unknown(
        requested_target
    ):
        return

    # --------------------------------------------------------
    # INSERT does not use WHERE.
    #
    # Target/value consistency is handled through the INSERT
    # assignments instead.
    # --------------------------------------------------------

    if operation == "INSERT":
        return

    predicates = _extract_predicates(
        sql
    )

    if not predicates:

        if not _is_all_target(
            requested_target
        ):

            mismatches.append(
                "TARGET_MISMATCH"
            )

        return

    normalized_target = (
        _normalize_sql_value(
            requested_target
        )
    )

    # If the user requested all records/employees and the predicates are existence
    # checks like IS NOT NULL, this is an all-target query, not a target mismatch.
    if _is_all_target(requested_target):
        if all(p.get("operator") in ("IS NOT NULL", "IS NULL") for p in predicates):
            return

    target_found = False

    for predicate in predicates:

        predicate_value = (
            _normalize_sql_value(
                predicate.get("value", "")
            )
        )

        # 1. Exact match
        if (
            predicate_value
            == normalized_target
        ):

            target_found = True
            break

        # 2. IN list values
        if (
            "values" in predicate
            and normalized_target in predicate["values"]
        ):
            target_found = True
            break

        # 3. LIKE operator or wildcard substring match
        op = str(predicate.get("operator", "")).upper()
        if "LIKE" in op or "%" in predicate_value or "_" in predicate_value:
            clean_val = predicate_value.replace("%", "").replace("_", "").strip()
            if clean_val and (clean_val in normalized_target or normalized_target in clean_val):
                target_found = True
                break

    if not target_found:

        mismatches.append(
            "TARGET_MISMATCH"
        )


# ============================================================
# SELECT field checking
# ============================================================

def _check_select_field(
    intent,
    sql,
    mismatches,
):

    requested_field = (
        intent.get("field")
    )

    if _is_unknown(
        requested_field
    ):
        return

    select_fields = (
        _extract_select_fields(
            sql
        )
    )

    if not select_fields:
        return

    normalized_requested = (
        _normalize_identifier(
            requested_field
        )
    )

    # SELECT * contains every field.
    if "*" in select_fields:
        return

    if normalized_requested not in select_fields:

        mismatches.append(
            "FIELD_MISMATCH"
        )


# ============================================================
# INSERT / UPDATE field-value checking
# ============================================================

def _check_write_field_value(
    operation,
    intent,
    sql,
    mismatches,
):

    requested_field = (
        intent.get("field")
    )

    requested_value = (
        intent.get("value")
    )

    if operation == "UPDATE":

        assignments = (
            _extract_update_assignments(
                sql
            )
        )

    elif operation == "INSERT":

        assignments = (
            _extract_insert_assignments(
                sql
            )
        )

    else:

        assignments = []

    if not assignments:
        return

    # --------------------------------------------------------
    # Field
    # --------------------------------------------------------

    if not _is_unknown(
        requested_field
    ):

        requested_field_normalized = (
            _normalize_identifier(
                requested_field
            )
        )

        field_found = any(
            _normalize_identifier(
                assignment["field"]
            )
            == requested_field_normalized

            for assignment
            in assignments
        )

        if not field_found:

            mismatches.append(
                "FIELD_MISMATCH"
            )

    # --------------------------------------------------------
    # Value
    # --------------------------------------------------------

    if not _is_unknown(
        requested_value
    ):

        normalized_requested_value = (
            _normalize_sql_value(
                requested_value
            )
        )

        value_found = False

        for assignment in assignments:

            sql_value = (
                _normalize_sql_value(
                    assignment["value"]
                )
            )

            # Exact value match.
            if (
                normalized_requested_value
                == sql_value
            ):

                value_found = True
                break

            # ------------------------------------------------
            # Arithmetic update
            # ------------------------------------------------
            #
            # balance = balance + 100
            # salary  = salary + 5000
            # price   = price - 50
            # ------------------------------------------------

            if re.search(
                rf"\+\s*"
                rf"{re.escape(normalized_requested_value)}"
                rf"\b",
                sql_value
            ):

                value_found = True
                break

            if re.search(
                rf"-\s*"
                rf"{re.escape(normalized_requested_value)}"
                rf"\b",
                sql_value
            ):

                value_found = True
                break

        if not value_found:

            mismatches.append(
                "VALUE_MISMATCH"
            )


# ============================================================
# Scope checking
# ============================================================

def _check_scope(
    intent,
    sql,
    mismatches,
):

    requested_scope = (
        intent.get("scope")
    )

    if _is_unknown(
        requested_scope
    ):
        return

    requested_scope = (
        _normalize_scope(
            requested_scope
        )
    )

    where_clause = (
        _extract_where(
            sql
        )
    )

    sql_scope = (
        "ALL_ROWS"
        if not where_clause
        else "FILTERED"
    )

    target = (
        intent.get("target")
    )

    # --------------------------------------------------------
    # Explicit all-target intent
    # --------------------------------------------------------

    if _is_all_target(
        target
    ):

        if sql_scope != "ALL_ROWS":

            predicates = _extract_predicates(sql)
            if not (predicates and all(p.get("operator") in ("IS NOT NULL", "IS NULL") for p in predicates)):
                mismatches.append(
                    "SCOPE_MISMATCH"
                )

        return

    # --------------------------------------------------------
    # INSERT does not have WHERE scope semantics.
    #
    # Do not invent a scope mismatch simply because an INSERT
    # lacks WHERE.
    # --------------------------------------------------------

    if (
        _normalize_operation(
            intent.get("operation")
        )
        == "INSERT"
    ):

        return

    # --------------------------------------------------------
    # Single-row intent
    # --------------------------------------------------------

    if requested_scope == "ONE_ROW":

        if sql_scope == "ALL_ROWS":

            mismatches.append(
                "SCOPE_MISMATCH"
            )

        return

    # --------------------------------------------------------
    # Multiple/all-row intent
    # --------------------------------------------------------

    if requested_scope in {
        "MULTIPLE_ROWS",
        "ALL_ROWS",
    }:

        if sql_scope == "ALL_ROWS":

            if requested_scope != "ALL_ROWS":

                mismatches.append(
                    "SCOPE_MISMATCH"
                )

        return


# ============================================================
# Main checker
# ============================================================

def check_intent_sql(
    intent,
    sql,
):

    mismatches = []

    if not intent:

        return {
            "match": False,
            "mismatches": [
                "UNKNOWN_INTENT"
            ],
        }

    if isinstance(intent, str):
        try:
            from intent_analyzer import analyze_intent
            intent = analyze_intent(intent)
        except Exception:
            intent = {
                "operation": "UNKNOWN",
                "target": intent,
                "field": "unknown",
                "value": "unknown",
                "scope": "unknown",
            }

    if not isinstance(intent, dict):
        return {
            "match": False,
            "mismatches": [
                "UNKNOWN_INTENT"
            ],
        }

    if not sql:

        return {
            "match": False,
            "mismatches": [
                "UNKNOWN_SQL"
            ],
        }

    operation = (
        _normalize_operation(
            intent.get("operation")
        )
    )

    # --------------------------------------------------------
    # SQL operation
    # --------------------------------------------------------

    sql_match = re.search(
        r"^\s*(?:--.*?\n\s*)*"
        r"([A-Za-z]+)",
        sql,
        flags=re.IGNORECASE,
    )

    sql_operation = (
        _normalize_operation(
            sql_match.group(1)
        )
        if sql_match
        else "UNKNOWN"
    )

    if (
        operation != "UNKNOWN"
        and sql_operation != "UNKNOWN"
        and operation != sql_operation
    ):

        mismatches.append(
            "OPERATION_MISMATCH"
        )

    # --------------------------------------------------------
    # SELECT
    # --------------------------------------------------------

    if sql_operation == "SELECT":

        _check_filter_target(
            operation,
            intent,
            sql,
            mismatches,
        )

        _check_select_field(
            intent,
            sql,
            mismatches,
        )

    # --------------------------------------------------------
    # UPDATE
    # --------------------------------------------------------

    elif sql_operation == "UPDATE":

        _check_filter_target(
            operation,
            intent,
            sql,
            mismatches,
        )

        _check_write_field_value(
            sql_operation,
            intent,
            sql,
            mismatches,
        )

    # --------------------------------------------------------
    # INSERT
    # --------------------------------------------------------

    elif sql_operation == "INSERT":

        # INSERT target is represented by inserted field/value
        # assignments rather than WHERE predicates.
        _check_write_field_value(
            sql_operation,
            intent,
            sql,
            mismatches,
        )

    # --------------------------------------------------------
    # DELETE
    # --------------------------------------------------------

    elif sql_operation == "DELETE":

        _check_filter_target(
            operation,
            intent,
            sql,
            mismatches,
        )

    # --------------------------------------------------------
    # Scope
    # --------------------------------------------------------

    _check_scope(
        intent,
        sql,
        mismatches,
    )

    return {
        "match": len(mismatches) == 0,
        "mismatches": mismatches,
    }


# ============================================================
# Backward-compatible alias
# ============================================================

def check_intent_sql_consistency(
    intent,
    sql,
):

    return check_intent_sql(
        intent,
        sql,
    )


# ============================================================
# Standalone tests
# ============================================================

if __name__ == "__main__":

    tests = [

        {
            "name": "All employees",

            "intent": {
                "operation": "UPDATE",
                "target": "all employees",
                "field": "salary",
                "value": "100",
                "scope": "all rows",
            },

            "sql": """
                UPDATE employees
                SET salary = salary + 100;
            """,

            "expected_match": True,
        },

        {
            "name": "All customers",

            "intent": {
                "operation": "UPDATE",
                "target": "all customers",
                "field": "balance",
                "value": "100",
                "scope": "all rows",
            },

            "sql": """
                UPDATE customers
                SET balance = balance + 100;
            """,

            "expected_match": True,
        },

        {
            "name": "All products",

            "intent": {
                "operation": "UPDATE",
                "target": "all products",
                "field": "price",
                "value": "50",
                "scope": "all rows",
            },

            "sql": """
                UPDATE products
                SET price = price + 50;
            """,

            "expected_match": True,
        },

        {
            "name": "Every account",

            "intent": {
                "operation": "UPDATE",
                "target": "every account",
                "field": "balance",
                "value": "10",
                "scope": "all rows",
            },

            "sql": """
                UPDATE accounts
                SET balance = balance + 10;
            """,

            "expected_match": True,
        },

        {
            "name": "Every record",

            "intent": {
                "operation": "UPDATE",
                "target": "every record",
                "field": "value",
                "value": "5",
                "scope": "all rows",
            },

            "sql": """
                UPDATE records
                SET value = value + 5;
            """,

            "expected_match": True,
        },

        {
            "name": "Entire table",

            "intent": {
                "operation": "UPDATE",
                "target": "entire table",
                "field": "score",
                "value": "1",
                "scope": "all rows",
            },

            "sql": """
                UPDATE data
                SET score = score + 1;
            """,

            "expected_match": True,
        },

        {
            "name": "All customers but filtered SQL",

            "intent": {
                "operation": "UPDATE",
                "target": "all customers",
                "field": "balance",
                "value": "100",
                "scope": "all rows",
            },

            "sql": """
                UPDATE customers
                SET balance = balance + 100
                WHERE membership = 'premium';
            """,

            "expected_match": False,
        },

        {
            "name": "Specific target without WHERE",

            "intent": {
                "operation": "UPDATE",
                "target": "customer42",
                "field": "balance",
                "value": "100",
                "scope": "one row",
            },

            "sql": """
                UPDATE customers
                SET balance = balance + 100;
            """,

            "expected_match": False,
        },

        {
            "name": "Correct customer target",

            "intent": {
                "operation": "UPDATE",
                "target": "customer42",
                "field": "balance",
                "value": "100",
                "scope": "one row",
            },

            "sql": """
                UPDATE customers
                SET balance = balance + 100
                WHERE customer_id = 'customer42';
            """,

            "expected_match": True,
        },

        {
            "name": "Wrong customer target",

            "intent": {
                "operation": "UPDATE",
                "target": "customer42",
                "field": "balance",
                "value": "100",
                "scope": "one row",
            },

            "sql": """
                UPDATE customers
                SET balance = balance + 100
                WHERE customer_id = 'customer99';
            """,

            "expected_match": False,
        },

        {
            "name": "Arithmetic update",

            "intent": {
                "operation": "UPDATE",
                "target": "unknown",
                "field": "balance",
                "value": "100",
                "scope": "multiple rows",
            },

            "sql": """
                UPDATE customers
                SET balance = balance + 100
                WHERE membership = 'premium';
            """,

            "expected_match": True,
        },

        {
            "name": "Correct SELECT field",

            "intent": {
                "operation": "SELECT",
                "target": "unknown",
                "field": "balance",
                "value": "unknown",
                "scope": "multiple rows",
            },

            "sql": """
                SELECT balance
                FROM customers
                WHERE membership = 'premium';
            """,

            "expected_match": True,
        },

        # ----------------------------------------------------
        # New regression test: qualified SELECT identifier
        # ----------------------------------------------------

        {
            "name": "Qualified SELECT field",

            "intent": {
                "operation": "SELECT",
                "target": "Arun",
                "field": "salary",
                "value": "unknown",
                "scope": "one row",
            },

            "sql": """
                SELECT e.salary
                FROM employees AS e
                WHERE e.name = 'Arun';
            """,

            "expected_match": True,
        },

        # ----------------------------------------------------
        # New regression test: generic INSERT
        # ----------------------------------------------------

        {
            "name": "INSERT field/value",

            "intent": {
                "operation": "INSERT",
                "target": "unknown",
                "field": "salary",
                "value": "50000",
                "scope": "multiple rows",
            },

            "sql": """
                INSERT INTO employees
                (name, salary, department)
                VALUES
                ('TestUser', 50000, 'Engineering');
            """,

            "expected_match": True,
        },
    ]

    passed = 0

    print("=" * 70)
    print("INTENT-SQL CHECKER TESTS")
    print("=" * 70)

    for index, test in enumerate(
        tests,
        start=1
    ):

        result = check_intent_sql(
            test["intent"],
            test["sql"],
        )

        actual = result[
            "match"
        ]

        expected = test[
            "expected_match"
        ]

        success = (
            actual == expected
        )

        if success:
            passed += 1

        print(
            f"TEST {index}: "
            f"{test['name']}"
        )

        print(
            f"  Expected: "
            f"{expected}"
        )

        print(
            f"  Actual:   "
            f"{actual}"
        )

        print(
            f"  Mismatches: "
            f"{result['mismatches']}"
        )

        print(
            f"  "
            f"{'PASS' if success else 'FAIL'}"
        )

        print()

    print("=" * 70)

    print(
        f"RESULT: "
        f"{passed}/{len(tests)} "
        f"tests passed"
    )

    print("=" * 70)
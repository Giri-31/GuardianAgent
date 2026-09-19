"""
GuardianAgent - Intent Analyzer

Converts a natural-language database request into:

{
    "operation": SELECT / INSERT / UPDATE / DELETE / UNKNOWN,
    "target": ...,
    "field": ...,
    "value": ...,
    "scope": single row / multiple rows / all rows / unknown
}

Design principles
-----------------

1. Schema independent
2. No hardcoded database names
3. No hardcoded table names
4. No hardcoded application entity names
5. No hardcoded field names
6. No hardcoded application values
7. Conservative parsing
8. Deterministic fallback for reproducible experiments
9. Optional Gemini analysis
10. GUARDIAN_DISABLE_LLM=1 disables Gemini completely

Important research principle
----------------------------

This module does NOT try to guess information that is not
explicitly recoverable from language structure.

Unknown is preferable to an unsafe guess.

The deterministic parser provides structural intent signals.
Final safety verification is performed downstream using
SQL semantics, database context, scope, impact, and
intent-SQL consistency.
"""

import json
import os
import re


# ============================================================
# Configuration
# ============================================================

MODEL_NAME = os.getenv(
    "GUARDIAN_INTENT_MODEL",
    "gemini-3.8-flash",
)

DISABLE_LLM = os.getenv(
    "GUARDIAN_DISABLE_LLM",
    "0",
).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


# ============================================================
# Gemini Client
# ============================================================

_client = None


def _get_client():
    """
    Lazily create the Gemini client.

    Gemini is completely bypassed when
    GUARDIAN_DISABLE_LLM=1.
    """

    global _client

    if DISABLE_LLM:
        return None

    if _client is not None:
        return _client

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        return None

    try:
        from google import genai

        _client = genai.Client(
            api_key=api_key
        )

        return _client

    except Exception:
        return None


def _safe_text(response):
    """
    Safely extract text from a Gemini response.

    Accessing response.text raises an exception when the model
    returns no output (e.g. safety filter block).  This helper
    extracts text via the candidates list first so that callers
    can handle empty responses without crashing.
    """

    try:
        text = response.text
        if text:
            return text.strip()
    except Exception:
        pass

    try:
        for candidate in (response.candidates or []):
            for part in (candidate.content.parts or []):
                t = getattr(part, "text", None)
                if t:
                    return t.strip()
    except Exception:
        pass

    return ""


# ============================================================
# Canonical Intent Schema
# ============================================================

VALID_OPERATIONS = {
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "UNKNOWN",
}

VALID_SCOPES = {
    "single row",
    "multiple rows",
    "all rows",
    "unknown",
}


def _empty_intent():
    """Return a canonical unknown intent."""

    return {
        "operation": "UNKNOWN",
        "target": "unknown",
        "field": "unknown",
        "value": "unknown",
        "scope": "unknown",
    }


# ============================================================
# Generic Helpers
# ============================================================

def _clean(value):
    """
    Normalize an extracted textual value.

    No schema-specific semantic knowledge is applied.
    """

    if value is None:
        return "unknown"

    value = str(value).strip()

    if not value:
        return "unknown"

    return value.strip(
        " \t\r\n.,!?;:"
    )


def _is_unknown(value):
    """Check whether a value represents unknown information."""

    if value is None:
        return True

    return str(value).strip().lower() in {
        "",
        "unknown",
        "none",
        "null",
    }


# ============================================================
# Normalization
# ============================================================

def _normalize_intent(intent):
    """
    Normalize any intent dictionary into the canonical schema.
    """

    if not isinstance(intent, dict):
        return _empty_intent()

    operation = str(
        intent.get(
            "operation",
            "UNKNOWN",
        )
    ).strip().upper()

    if operation not in VALID_OPERATIONS:
        operation = "UNKNOWN"

    target = _clean(
        intent.get("target")
    )

    field = _clean(
        intent.get("field")
    )

    value = _clean(
        intent.get("value")
    )

    scope = str(
        intent.get(
            "scope",
            "unknown",
        )
    ).strip().lower()

    scope_aliases = {

        "one row":
            "single row",

        "one record":
            "single row",

        "single record":
            "single row",

        "many rows":
            "multiple rows",

        "many records":
            "multiple rows",

        "several rows":
            "multiple rows",

        "several records":
            "multiple rows",

        "multiple records":
            "multiple rows",

        "all records":
            "all rows",

        "every record":
            "all rows",

        "every row":
            "all rows",

        "entire table":
            "all rows",

        "whole table":
            "all rows",
    }

    scope = scope_aliases.get(
        scope,
        scope,
    )

    if scope not in VALID_SCOPES:
        scope = "unknown"

    return {
        "operation": operation,
        "target": target,
        "field": field,
        "value": value,
        "scope": scope,
    }


# ============================================================
# Operation Detection
# ============================================================

def _detect_operation(text):
    """
    Detect the requested database operation.

    Only generic linguistic patterns are used.
    """

    text_lower = text.lower()

    # --------------------------------------------------------
    # DELETE
    # --------------------------------------------------------

    delete_patterns = [
        r"\bdelete\b",
        r"\bremove\b",
        r"\berase\b",
        r"\bdestroy\b",
    ]

    if any(
        re.search(
            pattern,
            text_lower,
        )
        for pattern in delete_patterns
    ):
        return "DELETE"

    # --------------------------------------------------------
    # UPDATE
    # --------------------------------------------------------

    update_patterns = [
        r"\bupdate\b",
        r"\bchange\b",
        r"\bmodify\b",
        r"\bincrease\b",
        r"\bdecrease\b",
        r"\braise\b",
        r"\blower\b",
        r"\bpromote\b",
        r"\bdemote\b",
        r"\bassign\b",
        r"\bset\b",
    ]

    if any(
        re.search(
            pattern,
            text_lower,
        )
        for pattern in update_patterns
    ):
        return "UPDATE"

    # --------------------------------------------------------
    # INSERT
    # --------------------------------------------------------

    insert_patterns = [
        r"\binsert\b",
        r"\badd\b",
        r"\bregister\b",
        r"\bappend\b",
        r"\bcreate\b",
    ]

    if any(
        re.search(
            pattern,
            text_lower,
        )
        for pattern in insert_patterns
    ):
        return "INSERT"

    # --------------------------------------------------------
    # SELECT
    # --------------------------------------------------------

    select_patterns = [
        r"\bselect\b",
        r"\bshow\b",
        r"\blist\b",
        r"\bdisplay\b",
        r"\bfind\b",
        r"\bget\b",
        r"\bfetch\b",
        r"\bretrieve\b",
        r"\bview\b",
        r"\blookup\b",
        r"\bwhat\b",
        r"\bwhich\b",
        r"\bhow\s+many\b",
        r"\bcount\b",
    ]

    if any(
        re.search(
            pattern,
            text_lower,
        )
        for pattern in select_patterns
    ):
        return "SELECT"

    return "UNKNOWN"


# ============================================================
# Filter Extraction
# ============================================================

def _extract_filter(text):
    """
    Extract generic field/value relationships.

    Supported forms:

        where FIELD is VALUE
        where FIELD equals VALUE
        where FIELD = VALUE
        with FIELD VALUE
        in the VALUE FIELD
        FIELD = VALUE

    No application-specific field or value names are used.
    """

    # --------------------------------------------------------
    # 1. WHERE FIELD OPERATOR VALUE
    #
    # Example:
    #
    # where score is 100
    #
    # -> field = score
    # -> value = 100
    # --------------------------------------------------------

    match = re.search(
        r"\bwhere\s+"
        r"([A-Za-z_][A-Za-z0-9_]*)"
        r"\s*"
        r"(?:is|equals|=|==|contains|like)"
        r"\s*"
        r"([A-Za-z0-9_.%+\-]+)",
        text,
        flags=re.IGNORECASE,
    )

    if match:

        return (
            match.group(1),
            _clean(
                match.group(2)
            ),
        )

    # --------------------------------------------------------
    # 2. FIELD = VALUE
    # --------------------------------------------------------

    match = re.search(
        r"\b"
        r"([A-Za-z_][A-Za-z0-9_]*)"
        r"\s*=\s*"
        r"([A-Za-z0-9_.%+\-]+)",
        text,
        flags=re.IGNORECASE,
    )

    if match:

        return (
            match.group(1),
            _clean(
                match.group(2)
            ),
        )

    # --------------------------------------------------------
    # 3. WITH FIELD VALUE
    # --------------------------------------------------------

    match = re.search(
        r"\bwith\s+"
        r"([A-Za-z_][A-Za-z0-9_]*)"
        r"\s+"
        r"([A-Za-z0-9_.%+\-]+)"
        r"(?=\s|[.,!?;:]|$)",
        text,
        flags=re.IGNORECASE,
    )

    if match:

        return (
            match.group(1),
            _clean(
                match.group(2)
            ),
        )

    # --------------------------------------------------------
    # 4. IN THE VALUE FIELD
    #
    # Example:
    #
    # in the premium category
    #
    # -> field = category
    # -> value = premium
    # --------------------------------------------------------

    match = re.search(
        r"\bin\s+"
        r"(?:the\s+)?"
        r"([A-Za-z][A-Za-z0-9_-]*)"
        r"\s+"
        r"([A-Za-z][A-Za-z0-9_-]*)"
        r"(?=\s|[.,!?;:]|$)",
        text,
        flags=re.IGNORECASE,
    )

    if match:

        return (
            match.group(2),
            _clean(
                match.group(1)
            ),
        )

    return None, None


# ============================================================
# Collection / Filter Detection
# ============================================================

def _contains_filter_structure(text):
    """
    Detect explicit conditional/filter language.

    This is structural and schema independent.
    """

    patterns = [
        r"\bwhere\b",
        r"\bwhose\b",
        r"\bwith\b",
        r"\bmatching\b",
        r"\bthat\s+have\b",
        r"\bthat\s+has\b",
        r"\bwherever\b",
    ]

    return any(
        re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )
        for pattern in patterns
    )


# ============================================================
# Explicit Identifier Extraction
# ============================================================

def _extract_explicit_identifier(text):
    """
    Extract explicit row identifiers.

    Examples:

        record 17
        row 17
        id 17
        identifier 17

    A word boundary is required after the marker.

    Therefore:

        record

    can match, but:

        records

    cannot be interpreted as:

        record + s
    """

    pattern = re.compile(
        r"\b"
        r"(?:record|row|id|identifier)"
        r"\b"
        r"\s*"
        r"(?:number|no\.?)?"
        r"\s*"
        r"([A-Za-z0-9_-]+)"
        r"(?=\s|[.,!?;:]|$)",
        flags=re.IGNORECASE,
    )

    match = pattern.search(
        text
    )

    if not match:
        return "unknown"

    candidate = _clean(
        match.group(1)
    )

    if _is_unknown(candidate):
        return "unknown"

    if candidate.lower() in {
        "where",
        "with",
        "is",
        "equals",
        "that",
        "which",
    }:
        return "unknown"

    return candidate


# ============================================================
# Descriptor + Identifier
# ============================================================

def _extract_descriptor_identifier(text):
    """
    Extract a numeric identifier after a generic descriptor.

    Examples:

        account 42
        customer 17
        product 7
        item 9

    The descriptor itself is not treated as a database
    entity definition.

    This is purely a linguistic WORD + NUMBER pattern.
    """

    pattern = re.compile(
        r"\b"
        r"[A-Za-z][A-Za-z0-9_-]*"
        r"\s+"
        r"(\d+)"
        r"(?=\s|[.,!?;:]|$)",
        flags=re.IGNORECASE,
    )

    for match in pattern.finditer(
        text
    ):

        prefix = text[
            :match.start()
        ]

        # Do not treat assignment values as identifiers.
        if re.search(
            r"\b(?:to|as|set)\s*$",
            prefix,
            flags=re.IGNORECASE,
        ):
            continue

        return match.group(1)

    return "unknown"


# ============================================================
# Possessive Target
# ============================================================

def _extract_possessive_target(text):
    """
    Extract:

        X's FIELD

    -> X
    """

    match = re.search(
        r"\b"
        r"([A-Za-z][A-Za-z0-9_-]*)"
        r"'s"
        r"(?=\s|[.,!?;:]|$)",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return "unknown"

    return _clean(
        match.group(1)
    )


# ============================================================
# "for TARGET" Extraction
# ============================================================

def _extract_for_target(text):
    """
    Extract a target following 'for'.

    Examples:

        update ... for Arun
        update ... for 42

    If a descriptor is followed by a numeric identifier,
    the identifier is returned.
    """

    matches = re.finditer(
        r"\bfor\s+"
        r"(?:the\s+)?"
        r"([A-Za-z][A-Za-z0-9_-]*|\d+)"
        r"(?=\s|[.,!?;:]|$)",
        text,
        flags=re.IGNORECASE,
    )

    for match in matches:

        candidate = _clean(
            match.group(1)
        )

        if candidate.lower() in {
            "all",
            "every",
            "each",
        }:
            continue

        after = text[
            match.end():
        ]

        numeric = re.match(
            r"\s+(\d+)"
            r"(?=\s|[.,!?;:]|$)",
            after,
        )

        if numeric:
            return numeric.group(1)

        return candidate

    return "unknown"


# ============================================================
# Direct Mutation Target
# ============================================================

def _extract_direct_mutation_target(text):
    """
    Extract a direct target after an UPDATE/DELETE operation.

    Examples:

        delete Arun
        update customer42

    Collection words are not accepted as targets.
    """

    operation_pattern = (
        r"(?:"
        r"delete|remove|erase|destroy|"
        r"update|change|modify|increase|decrease|"
        r"raise|lower|promote|demote|assign"
        r")"
    )

    match = re.search(
        r"\b"
        + operation_pattern
        + r"\s+"
        r"(?:the\s+)?"
        r"([A-Za-z][A-Za-z0-9_-]*)"
        r"(?=\s|[.,!?;:]|$)",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return "unknown"

    candidate = _clean(
        match.group(1)
    )

    if candidate.lower() in {
        "the",
        "a",
        "an",
        "all",
        "every",
        "each",
        "record",
        "records",
        "row",
        "rows",
        "field",
        "fields",
        "column",
        "columns",
        "attribute",
        "attributes",
    }:
        return "unknown"

    after = text[
        match.end():
    ]

    if re.match(
        r"\s+(?:field|column|attribute)\b",
        after,
        flags=re.IGNORECASE,
    ):
        return "unknown"

    return candidate


# ============================================================
# Target Extraction
# ============================================================

def _extract_target(text):
    """
    Extract a specific row target.

    Evidence priority:

        1. Possessive target
        2. Explicit identifier
        3. Filter-aware protection
        4. Descriptor + numeric identifier
        5. 'for TARGET'
        6. Direct mutation target

    A numeric value belonging to a filter must never be
    interpreted as a row target.
    """

    operation = _detect_operation(
        text
    )

    # --------------------------------------------------------
    # 1. Possessive target
    #
    # Example:
    #
    # customer17's name
    #
    # -> customer17
    # --------------------------------------------------------

    possessive = _extract_possessive_target(
        text
    )

    if possessive != "unknown":
        return possessive

    # --------------------------------------------------------
    # 2. Explicit row identifier
    #
    # Examples:
    #
    # record 17
    # row 17
    # id 17
    # identifier 17
    # --------------------------------------------------------

    explicit_identifier = _extract_explicit_identifier(
        text
    )

    if explicit_identifier != "unknown":
        return explicit_identifier

    # --------------------------------------------------------
    # 3. FILTER-AWARE PROTECTION
    #
    # This MUST happen before generic:
    #
    # WORD + NUMBER
    #
    # detection.
    #
    # Example:
    #
    # Show records where score is 100.
    #
    # score = field
    # 100   = filter value
    #
    # Therefore target = unknown.
    # --------------------------------------------------------

    filter_field, filter_value = _extract_filter(
        text
    )

    if (
        filter_field is not None
        and filter_value is not None
    ):
        return "unknown"

    # --------------------------------------------------------
    # 4. Descriptor + numeric identifier
    #
    # Examples:
    #
    # account 42
    # customer 17
    # product 7
    # item 9
    # --------------------------------------------------------

    descriptor_identifier = _extract_descriptor_identifier(
        text
    )

    if descriptor_identifier != "unknown":
        return descriptor_identifier

    # --------------------------------------------------------
    # 5. "for TARGET"
    # --------------------------------------------------------

    for_target = _extract_for_target(
        text
    )

    if for_target != "unknown":
        return for_target

    # --------------------------------------------------------
    # 6. Direct mutation target
    # --------------------------------------------------------

    if operation in {
        "UPDATE",
        "DELETE",
    }:

        direct_target = _extract_direct_mutation_target(
            text
        )

        if direct_target != "unknown":
            return direct_target

    return "unknown"


# ============================================================
# Field Extraction
# ============================================================

def _extract_explicit_field(text):
    """
    Extract:

        FIELD field
        FIELD column
        FIELD attribute
    """

    match = re.search(
        r"\b"
        r"([A-Za-z_][A-Za-z0-9_]*)"
        r"\s+"
        r"(?:field|column|attribute)"
        r"(?=\s|[.,!?;:]|$)",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return "unknown"

    candidate = _clean(
        match.group(1)
    )

    if candidate.lower() in {
        "the",
        "a",
        "an",
    }:
        return "unknown"

    return candidate


def _extract_possessive_field(text):
    """
    Extract:

        X's FIELD

    -> FIELD
    """

    match = re.search(
        r"\b"
        r"[A-Za-z][A-Za-z0-9_-]*"
        r"'s\s+"
        r"([A-Za-z_][A-Za-z0-9_]*)"
        r"(?=\s|[.,!?;:]|$)",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return "unknown"

    return _clean(
        match.group(1)
    )


def _extract_operation_field(text):
    """
    Extract a field after a mutation verb.

    Examples:

        update FIELD to VALUE
        change FIELD to VALUE
        modify FIELD
    """

    operation_pattern = (
        r"(?:"
        r"change|update|modify|set|increase|decrease|"
        r"raise|lower|promote|demote|assign"
        r")"
    )

    match = re.search(
        r"\b"
        + operation_pattern
        + r"\s+"
        r"(?:the\s+)?"
        r"([A-Za-z_][A-Za-z0-9_]*)"
        r"(?=\s|[.,!?;:]|$)",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return "unknown"

    candidate = _clean(
        match.group(1)
    )

    if candidate.lower() in {
        "record",
        "records",
        "row",
        "rows",
        "field",
        "fields",
        "column",
        "columns",
        "attribute",
        "attributes",
    }:
        return "unknown"

    after = text[
        match.end():
    ]

    if re.match(
        r"\s+(?:field|column|attribute)\b",
        after,
        flags=re.IGNORECASE,
    ):
        return candidate

    if re.search(
        r"\b(?:to|as)\b",
        after,
        flags=re.IGNORECASE,
    ):
        return candidate

    return "unknown"


def _extract_field(text):

    field = _extract_explicit_field(
        text
    )

    if field != "unknown":
        return field

    field = _extract_possessive_field(
        text
    )

    if field != "unknown":
        return field

    field = _extract_operation_field(
        text
    )

    if field != "unknown":
        return field

    return "unknown"


# ============================================================
# Value Extraction
# ============================================================

def _extract_assignment_value(
    text,
    target="unknown",
):
    """
    Extract explicitly assigned values:

        to VALUE
        as VALUE
    """

    patterns = [
        r"\bto\s+([A-Za-z0-9_.%+\-]+)",
        r"\bas\s+([A-Za-z0-9_.%+\-]+)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        value = _clean(
            match.group(1)
        )

        if value != target:
            return value

    return "unknown"


def _extract_quoted_value(text):

    match = re.search(
        r"""['"]([^'"]+)['"]""",
        text,
    )

    if not match:
        return "unknown"

    return _clean(
        match.group(1)
    )


def _extract_value(
    text,
    target="unknown",
):

    value = _extract_assignment_value(
        text,
        target=target,
    )

    if value != "unknown":
        return value

    quoted = _extract_quoted_value(
        text
    )

    if quoted != "unknown":
        return quoted

    return "unknown"


# ============================================================
# Scope Detection
# ============================================================

def _detect_scope(text):
    """
    Determine requested row scope.

    Priority:

        1. Explicit filter
        2. Specific target
        3. Explicit multiple-row language
        4. Qualified all-collection language
        5. Unfiltered all-row language
        6. Explicit single-row language
        7. Unknown
    """

    # --------------------------------------------------------
    # 1. Explicit filter
    # --------------------------------------------------------

    filter_field, filter_value = _extract_filter(
        text
    )

    has_filter = (
        filter_field is not None
        and filter_value is not None
    )

    conditional_language = _contains_filter_structure(
        text
    )

    if has_filter or conditional_language:
        return "multiple rows"

    # --------------------------------------------------------
    # 2. Specific target
    # --------------------------------------------------------

    target = _extract_target(
        text
    )

    if target != "unknown":
        return "single row"

    # --------------------------------------------------------
    # 3. Explicit multiple-row language
    # --------------------------------------------------------

    multiple_patterns = [
        r"\bmultiple\b",
        r"\bseveral\b",
        r"\bmany\b",
        r"\bvarious\b",
    ]

    if any(
        re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )
        for pattern in multiple_patterns
    ):
        return "multiple rows"

    # --------------------------------------------------------
    # 4. Qualified "all" collection
    #
    # Example:
    #
    # all inactive employees
    # all active accounts
    #
    # These describe a subset, not the entire collection.
    # --------------------------------------------------------

    qualified_all = re.search(
        r"\ball\s+"
        r"([A-Za-z][A-Za-z0-9_-]*)"
        r"\s+"
        r"([A-Za-z][A-Za-z0-9_-]*)"
        r"(?=\s|[.,!?;:]|$)",
        text,
        flags=re.IGNORECASE,
    )

    if qualified_all:
        return "multiple rows"

    # --------------------------------------------------------
    # 5. Unfiltered all-row expressions
    # --------------------------------------------------------

    unfiltered_all_patterns = [

        r"\ball\s+"
        r"[A-Za-z][A-Za-z0-9_-]*"
        r"(?=\s|[.,!?;:]|$)",

        r"\bevery\s+"
        r"[A-Za-z][A-Za-z0-9_-]*"
        r"(?=\s|[.,!?;:]|$)",

        r"\beach\s+"
        r"[A-Za-z][A-Za-z0-9_-]*"
        r"(?=\s|[.,!?;:]|$)",

        r"\bentire\s+table\b",

        r"\bwhole\s+table\b",
    ]

    if any(
        re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )
        for pattern in unfiltered_all_patterns
    ):
        return "all rows"

    # --------------------------------------------------------
    # 6. Explicit single-row language
    # --------------------------------------------------------

    single_patterns = [
        r"\ba particular\b",
        r"\ba specific\b",
        r"\bone record\b",
        r"\bone row\b",
        r"\bsingle record\b",
        r"\bsingle row\b",
    ]

    if any(
        re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )
        for pattern in single_patterns
    ):
        return "single row"

    return "unknown"


# ============================================================
# Deterministic Fallback
# ============================================================

def _fallback_intent(user_request):
    """
    Deterministic rule-based intent extraction.
    """

    if not user_request:
        return _empty_intent()

    text = str(
        user_request
    ).strip()

    operation = _detect_operation(
        text
    )

    # --------------------------------------------------------
    # Extract filter first.
    # --------------------------------------------------------

    filter_field, filter_value = _extract_filter(
        text
    )

    # --------------------------------------------------------
    # Target
    # --------------------------------------------------------

    target = _extract_target(
        text
    )

    # --------------------------------------------------------
    # Field
    # --------------------------------------------------------

    if filter_field is not None:

        field = filter_field

    else:

        field = _extract_field(
            text
        )

    # --------------------------------------------------------
    # Value
    # --------------------------------------------------------

    if filter_value is not None:

        value = filter_value

    else:

        value = _extract_value(
            text,
            target=target,
        )

    # --------------------------------------------------------
    # Scope
    # --------------------------------------------------------

    scope = _detect_scope(
        text
    )

    # --------------------------------------------------------
    # Safety normalization
    #
    # Target identifier must never become the modification
    # value.
    # --------------------------------------------------------

    if (
        target != "unknown"
        and value == target
    ):
        value = "unknown"

    return _normalize_intent(
        {
            "operation": operation,
            "target": target,
            "field": field,
            "value": value,
            "scope": scope,
        }
    )


# ============================================================
# Gemini Intent Analysis
# ============================================================

def _gemini_intent(user_request):
    """
    Optional Gemini-based intent extraction.

    Gemini failures automatically fall back to deterministic
    parsing.
    """

    client = _get_client()

    if client is None:
        return None

    prompt = f"""
You are an intent extraction component inside a database
safety verification system.

Convert the natural-language database request into JSON.

Return ONLY:

{{
  "operation": "SELECT|INSERT|UPDATE|DELETE|UNKNOWN",
  "target": "specific row/entity identifier or unknown",
  "field": "specific field or unknown",
  "value": "requested value or unknown",
  "scope": "single row|multiple rows|all rows|unknown"
}}

Rules:

1. Do not assume a particular database schema.
2. Do not invent table names.
3. Do not invent field names.
4. Do not invent entity names.
5. Do not invent identifiers.
6. Do not invent values.
7. Preserve explicitly stated identifiers.
8. Generic collection words such as "record",
   "records", "row", and "rows" are not themselves
   row identifiers.
9. A conditional request refers to the matching subset.
10. An explicitly unfiltered request for all records
    refers to all rows.
11. A specific identifier normally refers to one row.
12. A numeric value in a condition is a filter value,
    not a row target.
13. If information cannot be determined, return "unknown".
14. Do not infer database semantics that are not expressed.

Request:

{user_request}
"""

    try:

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
        )

        text = _safe_text(response)

        parsed = _extract_json(
            text
        )

        if parsed is None:
            return None

        return _normalize_intent(
            parsed
        )

    except Exception:
        return None


# ============================================================
# JSON Extraction
# ============================================================

def _extract_json(text):
    """
    Extract JSON from Gemini output.
    """

    if not text:
        return None

    text = str(
        text
    ).strip()

    # Remove markdown code fences.
    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"\s*```$",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = text.strip()

    # --------------------------------------------------------
    # Direct JSON
    # --------------------------------------------------------

    try:

        result = json.loads(
            text
        )

        if isinstance(result, dict):
            return result

    except Exception:
        pass

    # --------------------------------------------------------
    # Embedded JSON
    # --------------------------------------------------------

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1:
        return None

    try:

        result = json.loads(
            text[start:end + 1]
        )

        if isinstance(result, dict):
            return result

    except Exception:
        pass

    return None


# ============================================================
# Public API
# ============================================================

def analyze_intent(user_request):
    """
    Analyze a natural-language database request.

    Deterministic mode:

        GUARDIAN_DISABLE_LLM=1

    Normal mode:

        Gemini first
        deterministic fallback second
    """

    if not user_request:
        return _empty_intent()

    # --------------------------------------------------------
    # Reproducible deterministic mode
    # --------------------------------------------------------

    if DISABLE_LLM:

        return _fallback_intent(
            user_request
        )

    # --------------------------------------------------------
    # Optional Gemini
    # --------------------------------------------------------

    intent = _gemini_intent(
        user_request
    )

    if intent is not None:
        return intent

    # --------------------------------------------------------
    # Deterministic fallback
    # --------------------------------------------------------

    return _fallback_intent(
        user_request
    )


# ============================================================
# Standalone Tests
# ============================================================

if __name__ == "__main__":

    print("=" * 70)
    print("INTENT ANALYZER TESTS")
    print("=" * 70)

    print(
        f"\nLLM disabled: {DISABLE_LLM}"
    )

    print(
        f"Model: {MODEL_NAME}"
    )

    test_requests = [

        # ----------------------------------------------------
        # Original tests
        # ----------------------------------------------------

        "Change Arun's salary to 70000.",

        "Delete Arun from the company.",

        "Show me all employees in the IT department.",

        "Show me all inactive employees.",

        "Update customer42's status to active.",

        "Delete record 17.",

        "Increase product7's price to 1250.",

        "Show all records.",

        "Find users in the premium category.",

        "Update the status field for account 42.",

        "Find records where category is premium.",

        "Show users with status active.",

        "Update record 25.",

        # ----------------------------------------------------
        # Collection tests
        # ----------------------------------------------------

        "Show all users.",

        "Show all rows.",

        "Show every record.",

        "List every item.",

        "List all active accounts.",

        "Find all users with role admin.",

        # ----------------------------------------------------
        # Filter tests
        # ----------------------------------------------------

        "Find rows where type is premium.",

        "Find records where status = active.",

        "Show users with role admin.",

        "Find products in the electronics category.",

        "Show records where score is 100.",

        "Show records where status equals inactive.",

        # ----------------------------------------------------
        # Explicit identifier tests
        # ----------------------------------------------------

        "Delete row 31.",

        "Delete id 44.",

        "Delete identifier 99.",

        "Update account 42.",

        "Modify item 7.",

        "Set record 25.",

        # ----------------------------------------------------
        # Possessive / mutation tests
        # ----------------------------------------------------

        "Change customer17's name to John.",

        "Update the price field for item 7.",

        "Change the value column for row 12 to 500.",

        # ----------------------------------------------------
        # Single-row SELECT tests
        # ----------------------------------------------------

        "Show record 17.",

        "Find row 42.",

        "Retrieve id 91.",

        # ----------------------------------------------------
        # Explicit multiple-row tests
        # ----------------------------------------------------

        "Show multiple records.",

        "Show several rows.",

        "Show many entries.",
    ]

    for request in test_requests:

        print("\n" + "-" * 70)

        print("REQUEST:")
        print(request)

        print("\nINTENT:")

        print(
            analyze_intent(
                request
            )
        )
# GuardianAgent

### Consequence-Aware Safety Verification for LLM-Generated Database Actions

GuardianAgent is a research prototype for improving the safety of LLM-based database agents.

Large Language Models can generate syntactically valid SQL queries that are nevertheless unsafe because they may affect more data than the user intended, target the wrong records, perform an unintended operation, or cause excessive database impact.

GuardianAgent acts as a safety gateway between an LLM-based database agent and the database. Before a generated SQL query is executed, it analyzes the user's intent, SQL semantics, scope, and potential database impact to determine whether the action should be **ALLOWED, CONFIRMED, or BLOCKED**.

---

## Problem

An LLM may correctly understand a user's request but generate an over-scoped SQL query.

For example, consider:

**User request:**

> Change Arun's salary to 70000.

A safe query would be:

```sql
UPDATE employees
SET salary = 70000
WHERE name = 'Arun';

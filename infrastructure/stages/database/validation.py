"""Validate generated SQLite DDL in memory against the schema's structural contract."""

import re
import sqlite3


SQL_TYPES = {
    "string": "TEXT", "uuid": "TEXT", "date": "TEXT", "datetime": "TEXT", "json": "TEXT",
    "integer": "INTEGER", "boolean": "INTEGER", "number": "REAL",
}


def validate_sql_names(schema: dict) -> None:
    # SQLite identifiers are case-insensitive, unlike the IR dictionary keys.
    """Reject case-insensitive identifier collisions and SQLite-reserved names before generating SQL."""
    groups = [("tables", list(schema["entities"]))]
    groups.extend((name, list(entity["fields"])) for name, entity in schema["entities"].items())
    for label, names in groups:
        if len({name.lower() for name in names}) != len(names):
            raise ValueError(f"SQLite identifier case collision: {label}")
        if any(name.lower().startswith("sqlite_") for name in names):
            raise ValueError(f"SQLite reserved identifier prefix: {label}")


def validate_response(response: dict, expected_path: str) -> str:
    """Require the expected table file path and nonempty SQL content; return the accepted SQL text."""
    if not isinstance(response, dict) or set(response) != {"path", "content"}:
        raise ValueError("Implementation response must contain exactly path and content")
    if response["path"] != expected_path:
        raise ValueError(f"Expected implementation path: {expected_path}")
    if not isinstance(response["content"], str) or not response["content"].strip():
        raise ValueError("SQL content must be nonempty text")
    return response["content"]


def _create_table(connection, name: str, sql: str) -> None:
    """Execute exactly one authorized CREATE TABLE statement for the expected table in the validation database."""
    prefix = r"\A\s*(?:(?:--[^\n]*(?:\n|\Z)|/\*[\s\S]*?\*/)\s*)*CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+"
    if not re.match(prefix, sql, re.IGNORECASE):
        raise ValueError("Expected one CREATE TABLE IF NOT EXISTS statement")

    def authorize(action, first, second, _database, _source):
        """Allow only operations needed to create this table and its implicit uniqueness indexes."""
        if action == sqlite3.SQLITE_CREATE_TABLE:
            allowed = first == name
        elif action == sqlite3.SQLITE_CREATE_INDEX:
            allowed = second == name and first.startswith("sqlite_autoindex_")
        elif action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE):
            allowed = first == "sqlite_master"
        else:
            allowed = action in (sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION)
        return sqlite3.SQLITE_OK if allowed else sqlite3.SQLITE_DENY

    connection.set_authorizer(authorize)
    try:
        # execute(), unlike executescript(), rejects multiple statements.
        connection.execute(sql)
    except sqlite3.Error as error:
        raise ValueError(f"Invalid CREATE TABLE for {name}: {error}") from error
    finally:
        connection.set_authorizer(None)


def _check_table(connection, name: str, entity: dict) -> None:
    """Compare SQLite column, key, uniqueness, and foreign-key metadata with the entity definition."""
    columns = {row["name"]: row for row in connection.execute(f'PRAGMA table_info("{name}")')}
    if set(columns) != set(entity["fields"]):
        raise ValueError(f"SQL columns do not match schema: {name}")
    expected_unique = set()
    expected_foreign = set()
    for field_name, field in entity["fields"].items():
        column = columns[field_name]
        if column["type"].upper() != SQL_TYPES[field["type"]]:
            raise ValueError(f"SQL type does not match schema: {name}.{field_name}")
        if bool(column["notnull"]) != (not field["nullable"]):
            raise ValueError(f"SQL nullability does not match schema: {name}.{field_name}")
        if bool(column["pk"]) != field["primary_key"]:
            raise ValueError(f"SQL primary key does not match schema: {name}.{field_name}")
        if column["dflt_value"] is not None:
            raise ValueError(f"SQL defaults are not declared by this schema format: {name}.{field_name}")
        if field["unique"] or field["primary_key"]:
            expected_unique.add((field_name,))
        if field["references"]:
            target, target_field = field["references"].split(".")
            expected_foreign.add((field_name, target, target_field))
    actual_unique = set()
    for index in connection.execute(f'PRAGMA index_list("{name}")'):
        if index["unique"]:
            escaped = index["name"].replace('"', '""')
            actual_unique.add(tuple(row["name"] for row in connection.execute(f'PRAGMA index_info("{escaped}")')))
    # An INTEGER PRIMARY KEY uses the rowid instead of creating a unique index.
    actual_unique.update((column["name"],) for column in columns.values() if column["pk"])
    if actual_unique != expected_unique:
        raise ValueError(f"SQL uniqueness does not match schema: {name}")
    foreign = list(connection.execute(f'PRAGMA foreign_key_list("{name}")'))
    actual_foreign = {(row["from"], row["table"], row["to"]) for row in foreign}
    if actual_foreign != expected_foreign or any(row["seq"] != 0 for row in foreign):
        raise ValueError(f"SQL foreign keys do not match schema: {name}")
    if any(row[policy] not in {"NO ACTION", "RESTRICT"} for row in foreign for policy in ("on_update", "on_delete")):
        raise ValueError(f"SQL adds an undeclared cascading policy: {name}")


def validate_implementations(implementations: dict, schema: dict, complete: bool = False) -> None:
    # --- Extension point: semantic constraint verification --------------------
    # Metadata checks cover columns, types, flags, and FK edges. They do not
    # prove every natural-language value constraint; extend with domain probes.
    """Create tables in temporary in-memory SQLite and validate their structure and, when complete, combined foreign keys."""
    if complete and set(implementations) != set(schema["entities"]):
        raise ValueError("Missing table implementations")
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        for name, implementation in implementations.items():
            _create_table(connection, name, implementation["content"])
            _check_table(connection, name, schema["entities"][name])
        if complete:
            try:
                violations = list(connection.execute("PRAGMA foreign_key_check"))
            except sqlite3.Error as error:
                raise ValueError(f"Combined foreign-key schema is invalid: {error}") from error
            if violations:
                raise ValueError("Combined foreign-key validation failed")
    finally:
        connection.close()

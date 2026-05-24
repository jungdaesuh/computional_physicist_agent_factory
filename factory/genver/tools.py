"""Typed ReAct tool surface and validation helpers for generator-verifier turns."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

import sqlglot


class GenVerToolName(StrEnum):
    """Supported tool names exposed to the generator-verifier loop."""

    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    RUN_TESTS = "run_tests"
    QUERY_DB = "query_db"
    INSPECT_AST = "inspect_ast"
    VALIDATE_SQL = "validate_sql"
    WRITE_NOTES = "write_notes"
    FINISH = "finish"


@dataclass(frozen=True)
class ToolSpec:
    """Static tool contract shown to the ReAct agent."""

    name: GenVerToolName
    description: str
    required_inputs: tuple[str, ...]


@dataclass(frozen=True)
class ToolCall:
    """One requested ReAct tool invocation."""

    name: GenVerToolName
    arguments: Mapping[str, str]


@dataclass(frozen=True)
class ToolValidation:
    """Validation result for source or SQL proposed by the agent."""

    valid: bool
    diagnostic: str


REACT_TOOL_SURFACE: tuple[ToolSpec, ...] = (
    ToolSpec(GenVerToolName.READ_FILE, "Read a project file.", ("path",)),
    ToolSpec(GenVerToolName.WRITE_FILE, "Write a project file.", ("path", "content")),
    ToolSpec(GenVerToolName.RUN_TESTS, "Run a deterministic test command.", ("command",)),
    ToolSpec(GenVerToolName.QUERY_DB, "query_db against a read-only SQLite ledger.", ("sql",)),
    ToolSpec(GenVerToolName.INSPECT_AST, "Parse Python source with ast.", ("source",)),
    ToolSpec(GenVerToolName.VALIDATE_SQL, "Validate SQL with sqlglot.", ("sql",)),
    ToolSpec(GenVerToolName.WRITE_NOTES, "write_notes to the run journal.", ("content",)),
    ToolSpec(GenVerToolName.FINISH, "Finish the turn loop.", ("summary",)),
)


def react_tool_surface() -> tuple[ToolSpec, ...]:
    """Return the stable eight-tool ReAct surface."""
    return REACT_TOOL_SURFACE


def validate_tool_call(call: ToolCall) -> ToolValidation:
    """Validate that all required arguments for a tool are present and non-empty."""
    spec_by_name = {spec.name: spec for spec in REACT_TOOL_SURFACE}
    spec = spec_by_name[call.name]
    missing = tuple(key for key in spec.required_inputs if call.arguments.get(key, "") == "")
    if missing:
        return ToolValidation(False, f"missing required input(s): {', '.join(missing)}")
    return ToolValidation(True, "ok")


def validate_python_ast(source: str) -> ToolValidation:
    """Validate Python syntax using the standard AST parser."""
    try:
        ast.parse(source)
    except SyntaxError as exc:
        return ToolValidation(False, f"python syntax error: {exc.msg}")
    return ToolValidation(True, "ok")


def validate_sql(sql: str, *, dialect: str | None = None) -> ToolValidation:
    """Validate SQL syntax using sqlglot."""
    try:
        sqlglot.parse_one(sql, read=dialect)
    except sqlglot.errors.ParseError as exc:
        return ToolValidation(False, f"sql parse error: {exc}")
    return ToolValidation(True, "ok")


__all__ = [
    "GenVerToolName",
    "REACT_TOOL_SURFACE",
    "ToolCall",
    "ToolSpec",
    "ToolValidation",
    "react_tool_surface",
    "validate_python_ast",
    "validate_sql",
    "validate_tool_call",
]

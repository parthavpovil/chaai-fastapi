"""
§4.3 — Static guard: asyncio.gather must not be called with db.execute() coroutines.

Sharing a single AsyncSession across concurrent coroutines via asyncio.gather() causes
"This session is provisioning a new connection" / MissingGreenlet errors with asyncpg
because the underlying connection is not re-entrant.

This test walks every .py file under backend/app and backend/tests using the AST and
fails if it detects the pattern:
    asyncio.gather(..., <expr>.db.execute(...), ...)
    asyncio.gather(..., <expr>.db.scalar(...), ...)
    asyncio.gather(..., <expr>.db.scalars(...), ...)
    asyncio.gather(..., await <async_generator_expression>, ...)
or more generally any Call node inside asyncio.gather() whose function attribute
resolves to an attribute named "execute", "scalar", "scalars", "scalar_one_or_none",
or "get" on any receiver that contains "db" in its name.
"""
import ast
import pathlib
import pytest

_DB_METHODS = frozenset({
    "execute",
    "scalar",
    "scalars",
    "scalar_one",
    "scalar_one_or_none",
    "get",
    "run_sync",
})

_ROOT = pathlib.Path(__file__).parent.parent / "app"


def _is_db_call(node: ast.expr) -> bool:
    """Return True if node looks like <something_db>.execute(...) etc."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in _DB_METHODS:
        return False
    # Check the receiver contains "db" somewhere in its string representation
    receiver_src = ast.unparse(func.value)
    return "db" in receiver_src.lower() or "session" in receiver_src.lower()


def _gather_violations(tree: ast.AST, source_path: pathlib.Path) -> list[str]:
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match asyncio.gather(...)
        is_gather = (
            isinstance(func, ast.Attribute)
            and func.attr == "gather"
            and isinstance(func.value, ast.Name)
            and func.value.id == "asyncio"
        )
        if not is_gather:
            continue
        # Check each positional argument
        for arg in node.args:
            check = arg
            # Strip Await nodes — gather's args are usually plain coroutine calls, not awaited,
            # but guard against both forms.
            if isinstance(arg, ast.Await):
                check = arg.value
            if _is_db_call(check):
                violations.append(
                    f"{source_path}:{node.lineno}: "
                    f"asyncio.gather() contains a db session call ({ast.unparse(check)}). "
                    "Use sequential awaits or a fresh session per coroutine."
                )
    return violations


def _collect_py_files() -> list[pathlib.Path]:
    files = []
    for root in (_ROOT,):
        files.extend(root.rglob("*.py"))
    return files


@pytest.mark.parametrize("py_file", _collect_py_files(), ids=lambda p: str(p.relative_to(_ROOT.parent.parent)))
def test_no_gather_with_db_session(py_file: pathlib.Path) -> None:
    source = py_file.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(py_file))
    except SyntaxError:
        pytest.skip(f"Could not parse {py_file}")

    violations = _gather_violations(tree, py_file)
    assert not violations, "\n".join(violations)

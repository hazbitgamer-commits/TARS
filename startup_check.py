"""Catching the bug class that stopped TARS starting — before it ships.

What happened: a line was added near the top of main() that used
``threading``. main() imports threading further down its own body, and a
local import makes that name local for the WHOLE function — so the earlier
line raised UnboundLocalError and TARS wouldn't start at all. It then rolled
itself back to the last working version, correctly, taking four unrelated
fixes with it.

The galling part is that nothing caught it. py_compile was happy, because
the syntax is fine. Every test passed, because none of them run main(). It
is only ever visible when the function actually executes, which is exactly
the moment TARS is starting up and nobody is watching.

So this reads the code the way Python will: for every function, find the
names bound by an import inside it, and check nothing uses that name earlier
in the same function. It's a small rule and it's the difference between a
five-minute fix and an assistant that won't boot.
"""
import ast
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SKIP = {"runtime", "__pycache__", "backups", "workshop", "vault", "tools"}

passed = failed = 0


def check(name, got, want):
    global passed, failed
    ok = got == want
    passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
    print(f"  {'ok  ' if ok else 'FAIL'} {name}"
          + ("" if ok else f"\n         got {got!r}, wanted {want!r}"))


NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _own_scope(node: ast.AST):
    """Every node belonging to THIS function, not to one defined inside it.

    ast.walk can't do this: it descends into nested functions, and an import
    inside one of those binds a name in that function only. Getting this
    wrong means every helper defined inside another function looks like a
    bug, and a checker that cries wolf gets switched off.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, NESTED):
            continue
        yield child
        yield from _own_scope(child)


def shadowed_imports(tree: ast.AST) -> list:
    """[(function, name, used_on_line, imported_on_line)] — every place a
    function uses a name BEFORE its own import of that name binds it."""
    problems = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        bound = {}
        for inner in _own_scope(node):
            if isinstance(inner, (ast.Import, ast.ImportFrom)):
                for alias in inner.names:
                    local = (alias.asname or alias.name).split(".")[0]
                    # the EARLIEST import of that name, not whichever the
                    # walk reached first. A function may import the same
                    # module twice, and only the first one matters — taking
                    # a later one reported voice_check.py as broken when it
                    # imports json perfectly properly, higher up.
                    bound[local] = min(bound.get(local, inner.lineno),
                                       inner.lineno)
        if not bound:
            continue
        for inner in _own_scope(node):
            if (isinstance(inner, ast.Name) and isinstance(inner.ctx, ast.Load)
                    and inner.id in bound and inner.lineno < bound[inner.id]):
                problems.append((node.name, inner.id, inner.lineno,
                                 bound[inner.id]))
    return problems


def python_files() -> list:
    files = [p for p in BASE.glob("*.py")]
    files += [p for p in BASE.glob("skills/*/*.py")]
    return [p for p in files if not any(part in SKIP for part in p.parts)]


print("\nthe exact bug that stopped TARS booting")
sample = ast.parse(
    "def main():\n"
    "    threading.Thread(target=x).start()\n"
    "    import threading\n")
check("a name used before its own local import is caught",
      len(shadowed_imports(sample)), 1)

fine = ast.parse(
    "def main():\n"
    "    import threading\n"
    "    threading.Thread(target=x).start()\n")
check("importing first is fine", shadowed_imports(fine), [])

nested = ast.parse(
    "def outer():\n"
    "    threading.Thread(target=x).start()\n"
    "    def inner():\n"
    "        import threading\n")
check("an import in a nested function doesn't count against the outer one",
      shadowed_imports(nested), [])

top = ast.parse(
    "import threading\n"
    "def main():\n"
    "    threading.Thread(target=x).start()\n")
check("a module-level import is not a local one", shadowed_imports(top), [])

print("\nnow every file TARS actually runs")
found = []
for path in sorted(python_files()):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as bad:
        found.append((path.name, f"won't parse: {bad}"))
        continue
    for func, name, used, imported in shadowed_imports(tree):
        found.append((path.name,
                      f"{func}() uses '{name}' on line {used}, but imports it "
                      f"on line {imported} — UnboundLocalError at runtime"))

for where, what in found:
    print(f"       {where}: {what}")
check(f"no file uses a name before its own local import "
      f"({len(python_files())} files checked)", len(found), 0)

print("\nand the entry points are importable at all")
for module in ["main", "brain", "faces", "vision_track", "rewind",
               "highlights", "presence", "livestream", "model_router"]:
    try:
        __import__(module)
        ok = True
    except Exception as bad:
        ok = f"{type(bad).__name__}: {bad}"
    check(f"import {module}", ok, True)

print(f"\n{passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)

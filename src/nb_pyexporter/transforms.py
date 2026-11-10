"""Pure text/notebook transforms used by :class:`CleanPythonExporter`.

Everything here is independent of nbconvert's templating so it can be unit
tested directly and does not depend on whether IPython is installed.
"""

from __future__ import annotations

import ast
import logging
import re

import black

log = logging.getLogger(__name__)

# Cell magics whose body is *not* Python. Their contents are kept, but commented
# out, so nothing is silently lost and the script still parses.
NON_PYTHON_CELL_MAGICS = frozenset(
    {
        "bash", "sh", "script", "cmd", "powershell", "perl", "ruby", "python2",
        "html", "HTML", "javascript", "js", "latex", "markdown", "svg",
        "writefile", "file", "sql", "R",
    }
)

# YAML front matter: a block opened by `---` on the very first line and closed
# by `---` or `...`.
_FRONT_MATTER_RE = re.compile(
    r"\A\s*---[ \t]*\r?\n.*?^(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)", re.S | re.M
)
_CELL_MAGIC_RE = re.compile(r"^\s*%%([\w.]+)")
# `%magic`, `!cmd`, `x = %magic`, `x = !cmd`
_LINE_MAGIC_RE = re.compile(r"^\s*(?:[\w.,\s]+=\s*)?(?:%[A-Za-z_]|!)")
_IN_PROMPT_RE = re.compile(r"^[ \t]*# In\[[^\]]*\]:[ \t]*\r?\n?", re.M)
_SHEBANG_RE = re.compile(r"\A#![^\n]*\n")
_CODING_RE = re.compile(r"\A[ \t]*#.*coding[:=][^\n]*\n")
_EXCESS_BLANKS_RE = re.compile(r"\n{3,}")
# handcalcs v1 imports (`import handcalcs.render`, `from handcalcs import render`)
_HANDCALCS_V1_IMPORT_RE = re.compile(
    r"^[ \t]*(?:import[ \t]+handcalcs\.render|from[ \t]+handcalcs[ \t]+import[ \t]+render)"
    r"[ \t]*(?:#[^\n]*)?$",
    re.M,
)
_HANDCALCS_IMPORT_RE = re.compile(r"^import handcalcs[ \t]*$", re.M)

_LINE_MAGIC_METHODS = frozenset({"run_line_magic", "magic", "system", "getoutput"})


# --------------------------------------------------------------------------
# Cell-level transforms (applied to notebook cells before templating)
# --------------------------------------------------------------------------


def strip_front_matter(text: str) -> str:
    """Remove a leading YAML front-matter block, if present."""
    return _FRONT_MATTER_RE.sub("", text, count=1)


def _comment_out(lines: list[str]) -> list[str]:
    return [f"# {line}" if line.strip() else "#" for line in lines]


def strip_cell_magics(source: str) -> str:
    """Replace a leading ``%%magic args`` line with the plain cell body.

    Stacked magics (``%%time`` then ``%%render``) are all removed. If the magic
    is known not to contain Python (``%%bash``, ``%%html`` ...) the whole cell
    is commented out instead.
    """
    lines = source.splitlines()
    while True:
        idx = next((i for i, line in enumerate(lines) if line.strip()), None)
        if idx is None:
            break
        match = _CELL_MAGIC_RE.match(lines[idx])
        if not match:
            break
        if match.group(1) in NON_PYTHON_CELL_MAGICS:
            lines = lines[:idx] + _comment_out(lines[idx:])
            break
        lines = lines[:idx] + lines[idx + 1 :]
    return "\n".join(lines)


def strip_line_magics(source: str) -> str:
    """Drop ``%line_magic`` / ``!shell`` lines from a cell.

    Only runs when the cell doesn't already parse as Python, so a ``%`` or
    ``!`` that legitimately appears inside a string or expression is untouched.
    """
    try:
        ast.parse(source)
        return source
    except SyntaxError:
        pass
    kept = [line for line in source.splitlines() if not _LINE_MAGIC_RE.match(line)]
    return "\n".join(kept)


def clean_code_cell(source: str) -> str:
    return strip_line_magics(strip_cell_magics(source))


def clean_notebook(nb) -> None:
    """Mutate ``nb`` in place: strip front matter, cell magics and line magics."""
    # Front matter can only live in the first non-empty cell.
    for cell in nb.cells:
        if not cell.source.strip():
            continue
        cell.source = strip_front_matter(cell.source)
        break

    for cell in nb.cells:
        if cell.cell_type == "code":
            cell.source = clean_code_cell(cell.source)

    nb.cells = [cell for cell in nb.cells if cell.source.strip()]


# --------------------------------------------------------------------------
# Script-level transforms (applied to the exported text)
# --------------------------------------------------------------------------


def _is_get_ipython_call(node: ast.AST, methods: frozenset[str] | None = None) -> bool:
    """True for ``get_ipython().<method>(...)``."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Call)
        and isinstance(node.func.value.func, ast.Name)
        and node.func.value.func.id == "get_ipython"
        and (methods is None or node.func.attr in methods)
    )


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def unwrap_get_ipython(code: str) -> str:
    """Rewrite ``get_ipython()`` calls left behind by IPython's transformer.

    * ``get_ipython().run_cell_magic('render', 'params', 'a = 1\\nb = 2\\n')``
      becomes the plain lines ``a = 1`` / ``b = 2``.
    * line magics / shell escapes are removed (or become ``pass`` when nested
      inside a block, so the block stays valid).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code

    top_level = set(map(id, tree.body))
    # (start_line, end_line, replacement_lines); 1-indexed, inclusive.
    edits: list[tuple[int, int, list[str]]] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Expr, ast.Assign, ast.AnnAssign)):
            continue
        call = node.value
        if not _is_get_ipython_call(call):
            continue
        method = call.func.attr
        indent = " " * node.col_offset

        if method == "run_cell_magic" and isinstance(node, ast.Expr):
            args = [_const_str(a) for a in call.args]
            if len(args) != 3 or None in args:
                continue
            name, magic_args, body = args
            body_lines = body.splitlines()
            if name in NON_PYTHON_CELL_MAGICS:
                body_lines = _comment_out([f"%%{name} {magic_args}".rstrip(), *body_lines])
            replacement = [indent + line if line else line for line in body_lines]
        elif method in _LINE_MAGIC_METHODS:
            replacement = [] if id(node) in top_level else [indent + "pass"]
        else:
            continue
        edits.append((node.lineno, node.end_lineno, replacement))

    if not edits:
        return code

    lines = code.splitlines()
    for start, end, replacement in sorted(edits, reverse=True):
        lines[start - 1 : end] = replacement
    return "\n".join(lines) + "\n"


def strip_header(code: str) -> str:
    """Remove the shebang and ``# coding:`` lines the Python template emits."""
    code = _SHEBANG_RE.sub("", code, count=1)
    code = code.lstrip("\n")
    return _CODING_RE.sub("", code, count=1)


def strip_in_prompts(code: str) -> str:
    """Remove ``# In[14]:`` style cell reference comments."""
    return _IN_PROMPT_RE.sub("", code)


def update_handcalcs_import(code: str) -> str:
    """Rewrite handcalcs v1 imports to the v2.0 form ``import handcalcs``.

    Only the first resulting ``import handcalcs`` is kept.
    """
    code = _HANDCALCS_V1_IMPORT_RE.sub("import handcalcs", code)
    seen = False

    def _dedupe(match: re.Match) -> str:
        nonlocal seen
        if seen:
            return ""
        seen = True
        return match.group(0)

    return _HANDCALCS_IMPORT_RE.sub(_dedupe, code)


def normalize_whitespace(code: str) -> str:
    lines = [line.rstrip() for line in code.splitlines()]
    code = "\n".join(lines).strip("\n")
    return _EXCESS_BLANKS_RE.sub("\n\n", code) + "\n"


def format_with_black(code: str, source_name: str = "<notebook>") -> str:
    try:
        return black.format_str(code, mode=black.Mode())
    except Exception as exc:  # black raises several exception types
        log.warning("black could not format %s, leaving unformatted: %s", source_name, exc)
        return code


def postprocess(code: str, use_black: bool = True, source_name: str = "<notebook>") -> str:
    code = strip_header(code)
    code = strip_in_prompts(code)
    code = unwrap_get_ipython(code)
    code = update_handcalcs_import(code)
    code = normalize_whitespace(code)
    if use_black:
        code = format_with_black(code, source_name)
    return code

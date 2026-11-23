"""
Exporting a notebook as a handcalcs v2 script: one ``.py`` file that renders
(with ``HandCalcs``, the ``handcalcs`` command or YMPrint's ``_hc`` block) as
the notebook showed.

A script renders every line, but a notebook showed only its ``%%render``
cells and its Markdown, so each kind of cell is written differently:

- a Markdown cell becomes comment lines, which handcalcs shows as prose; its
  headings become handcalcs headings of the same level (``# H`` -> ``## H``),
  and its paragraphs are kept apart with ``# hc: -b``;
- a ``%%render`` (or ``%%source``) cell becomes its lines, without the magic.
  A comment command on its own line applied to the rest of its cell only, so
  after the cell the settings it changed are set back;
- any other code cell runs but is hidden, between ``# hc: -i`` and
  ``# hc: -s`` (``show_code`` shows it). Line magics and ``!`` commands are
  dropped, a non-Python cell magic (``%%bash``) is commented out, and a
  ``%render`` line is shown.

A notebook written for handcalcs v1 is converted to v2 first (see
``notebook.migrate_notebook``). Front matter in the first cell is dropped.
The script is checked to parse and is formatted with black.

The pieces of this module that strip magics come from nb_pyexporter.
"""

from __future__ import annotations

import ast
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from .convert import Note, change, warning
from .notebook import FileResult, Options, cell_text, migrate_notebook

log = logging.getLogger(__name__)

# Cell magics whose body is *not* Python. Their contents are kept, but commented
# out, so nothing is silently lost and the script still parses.
NON_PYTHON_CELL_MAGICS = frozenset(
    {
        "bash", "sh", "script", "cmd", "powershell", "perl", "ruby", "python2",
        "html", "HTML", "javascript", "js", "latex", "markdown", "svg",
        "writefile", "file", "sql", "R",
    }
)  # fmt: skip
# The cell magics whose cell handcalcs renders.
RENDER_MAGICS = frozenset({"render", "source"})

# YAML front matter: a block opened by `---` on the very first line and closed
# by `---` or `...`.
_FRONT_MATTER_RE = re.compile(
    r"\A\s*---[ \t]*\r?\n.*?^(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)", re.S | re.M
)
_CELL_MAGIC_RE = re.compile(r"^\s*%%([\w.]+)(.*)$")
# `%magic`, `!cmd`, `x = %magic`, `x = !cmd`
_LINE_MAGIC_RE = re.compile(r"^\s*(?:[\w.,\s]+=\s*)?(?:%[A-Za-z_]|!)")
# `%render x = a * b` (or %source): the one line handcalcs rendered.
_RENDER_LINE_RE = re.compile(r"^(\s*)%(?:render|source)[ \t]+(\S.*)$")
_EXCESS_BLANKS_RE = re.compile(r"\n{3,}")
_COMMAND_RE = re.compile(r"^\s*#\s*hc\s*:\s*(.*)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)|<img\b[^>]*>", re.I)
_LIST_ITEM_RE = re.compile(r"^\s*(?:[*+-]|\d+[.)])\s+")
_SET_OPTION_RE = re.compile(r"set_option\(\s*['\"](\w+)['\"]\s*,\s*([^)]+?)\s*\)")

HIDE = "# hc: -i"
SHOW = "# hc: -s"
BREAK = "# hc: -b"

# The settings a standalone comment command can change, by the flag that sets
# them, and their values in a fresh render (handcalcs' RenderContext).
FLAG_SETTINGS = {
    "-m": "multiline",
    "--multiline": "multiline",
    "-p": "param_line",
    "--param-line": "param_line",
    "-u": "units",
    "--units": "units",
    "-y": "sympy",
    "--sympy": "sympy",
    "--check": "check",
    "--boxed": "boxed",
}
VALUE_FLAGS = {
    "-f": "format_code",
    "--format-code": "format_code",
    "-c": "param_cols",
    "--param-cols": "param_cols",
    "--param_cols": "param_cols",
    "--mode": "mode",
}
DEFAULTS: dict[str, Any] = {
    "format_code": ".5g",
    "multiline": False,
    "param_line": False,
    "units": False,
    "sympy": False,
    "check": False,
    "boxed": False,
    "param_cols": 3,
    "mode": "full",
}


@dataclass
class ExportOptions(Options):
    # Show the code cells that the notebook didn't render.
    show_code: bool = False
    # Format the script with black.
    black: bool = True


@dataclass(frozen=True)
class Shown:
    """
    Lines of a hidden code cell that the notebook showed: a ``%render`` line,
    or the Markdown a cell displayed (as comment lines).
    """

    line: str


# --- Cells ---------------------------------------------------------------------


def strip_front_matter(text: str) -> str:
    """Remove a leading YAML front-matter block, if present."""
    return _FRONT_MATTER_RE.sub("", text, count=1)


def comment_out(lines: list[str]) -> list[str]:
    return [f"# {line}" if line.strip() else "#" for line in lines]


def cell_magics(source: str) -> tuple[list[tuple[str, str]], list[str]]:
    """
    The cell magics a cell starts with, as ``(name, arguments)``, and the
    lines after them. Magics stack: ``%%time`` then ``%%render``.
    """
    lines = source.splitlines()
    magics = []
    while True:
        idx = next((i for i, line in enumerate(lines) if line.strip()), None)
        if idx is None:
            break
        match = _CELL_MAGIC_RE.match(lines[idx])
        if not match:
            break
        magics.append((match.group(1), match.group(2).strip()))
        lines = lines[idx + 1 :]
    return magics, lines


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


def markdown_lines(text: str) -> list[str]:
    """
    A Markdown cell as comment lines: headings become handcalcs headings of
    the same level (handcalcs' ``##`` is the top level, so ``#`` gains one),
    paragraphs and list items are separated by ``# hc: -b`` (consecutive
    comment lines join into one paragraph), and fenced code is kept as
    comment text.
    """
    out: list[str] = []
    pending_break = False
    after_heading = False
    in_fence = False
    # An HTML line break starts a new paragraph.
    text = re.sub(r"[ \t]*<br\s*/?>[ \t]*", "\n\n", text, flags=re.I)
    for line in text.splitlines():
        line = line.rstrip()
        fence = bool(_FENCE_RE.match(line))
        if not line.strip() and not in_fence:
            pending_break = bool(out)
            continue
        heading = None if (in_fence or fence) else _HEADING_RE.match(line)
        if heading:
            out.append(f"#{heading.group(1)} {heading.group(2)}")
            pending_break = False
            after_heading = True
            continue
        list_item = not in_fence and bool(_LIST_ITEM_RE.match(line))
        if (pending_break or (list_item and out)) and not after_heading:
            # A paragraph, or a list item, starts a new paragraph.
            out.append(BREAK)
        pending_break = after_heading = False
        out.append(f"# {line}" if line.strip() else "#")
        if fence:
            in_fence = not in_fence
    return out


# --- Comment commands ----------------------------------------------------------


def literal(text: str) -> Any:
    try:
        return ast.literal_eval(text.strip())
    except (ValueError, SyntaxError):
        return None


def command_settings(command: str) -> tuple[dict[str, Any], str | None]:
    """
    The settings a standalone comment command (the text after ``# hc:``)
    changes, and ``"hide"``/``"show"`` when it is ``-i``/``-s``.
    """
    settings: dict[str, Any] = {}
    visibility = None
    try:
        tree = ast.parse(command)
        assignments = bool(tree.body) and all(
            isinstance(s, ast.Assign) for s in tree.body
        )
    except SyntaxError:
        assignments = False
    if assignments:
        for statement in tree.body:
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    value = literal(ast.unparse(statement.value))
                    if target.id == "ignore":
                        visibility = "hide" if value else "show"
                    else:
                        settings[target.id] = value
        return settings, visibility
    words = command.split()
    i = 0
    while i < len(words):
        word = words[i]
        if word in FLAG_SETTINGS:
            settings[FLAG_SETTINGS[word]] = True
        elif word in VALUE_FLAGS and i + 1 < len(words):
            key = VALUE_FLAGS[word]
            if key == "mode":
                # --mode takes its words up to the next flag.
                j = i + 1
                while j < len(words) and not words[j].startswith("-"):
                    j += 1
                settings[key] = " ".join(words[i + 1 : j])
                i = j
                continue
            settings[key] = words[i + 1]
            i += 1
        elif word in ("-i", "--ignore"):
            # A condition may follow; it may hide, so treat it as hiding.
            visibility = "hide"
            break
        elif word in ("-s", "--show"):
            # '-s <condition>' hides when the condition is false.
            visibility = "show" if i == len(words) - 1 else "hide"
            break
        i += 1
    return settings, visibility


def option_values(texts: list[str]) -> dict[str, Any]:
    """The literal ``set_option`` values in ``texts``, the last one of each."""
    values: dict[str, Any] = {}
    for text in texts:
        for name, value in _SET_OPTION_RE.findall(text):
            parsed = literal(value)
            if parsed is not None:
                values[name] = parsed
    return values


def reset_line(changed: set[str], before: dict[str, Any]) -> str | None:
    """
    A command setting each of ``changed`` back to its value before the cell
    (a ``set_option`` value, or handcalcs' default).
    """
    parts = []
    for key in sorted(changed):
        if key in DEFAULTS:
            value = before.get(key, DEFAULTS[key])
            text = f'"{value}"' if isinstance(value, str) else repr(value)
            parts.append(f"{key} = {text}")
    return f"# hc: {'; '.join(parts)}" if parts else None


def calc_lines(body: list[str], before: dict[str, Any]) -> list[str]:
    """
    A ``%%render`` cell's lines, followed by what sets back the settings its
    standalone commands changed (they applied to the rest of the cell only).
    """
    changed: set[str] = set()
    hidden = False
    for line in body:
        match = _COMMAND_RE.match(line)
        if not match:
            continue
        settings, visibility = command_settings(match.group(1))
        changed |= set(settings)
        if visibility:
            hidden = visibility == "hide"
    out = list(body)
    while out and not out[-1].strip():
        out.pop()
    if hidden:
        out.append(SHOW)
    reset = reset_line(changed, before)
    if reset:
        out.append(reset)
    return out


def hidden_lines(lines: list[str]) -> list[str]:
    """
    Code to hide. A top-level statement holding comment commands of its own
    (a decorated function, whose body handcalcs renders when it is called)
    is followed by ``# hc: -i``: a ``-s`` inside it would show what follows.
    """
    try:
        tree = ast.parse("\n".join(lines))
    except SyntaxError:
        return lines
    after = {
        statement.end_lineno
        for statement in tree.body
        if any(
            _COMMAND_RE.match(line)
            for line in lines[statement.lineno - 1 : statement.end_lineno]
        )
    }
    out = []
    for number, line in enumerate(lines, start=1):
        out.append(line)
        if number in after:
            out.append(HIDE)
    return out


# --- Displayed Markdown --------------------------------------------------------

# Format specs that Jinja's ``format`` filter (printf-style) reads the same.
_PRINTF_SPEC = re.compile(r"^[-+ 0#]*\d*(?:\.\d+)?[diouxXeEfFgG%]$")


def fstring_template(node: ast.expr) -> str | None:
    """
    A string or f-string as a handcalcs comment template: ``{x}`` becomes
    ``{{ x }}`` and ``{x:.2f}`` becomes ``{{ "%.2f"|format(x) }}``. None for
    an f-string handcalcs can't fill (another format spec, a conversion).
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if not isinstance(node, ast.JoinedStr):
        return None
    parts = []
    for value in node.values:
        if isinstance(value, ast.Constant):
            parts.append(str(value.value))
            continue
        if value.conversion != -1:
            return None
        expr = ast.unparse(value.value)
        if value.format_spec is None:
            parts.append(f"{{{{ {expr} }}}}")
            continue
        spec = fstring_template(value.format_spec)
        if spec is None or not _PRINTF_SPEC.match(spec):
            return None
        parts.append(f'{{{{ "%{spec}"|format({expr}) }}}}')
    return "".join(parts)


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute):
            return func.attr
        if isinstance(func, ast.Name):
            return func.id
    return ""


def displayed_markdown(statement: ast.stmt) -> str | None:
    """
    The Markdown template of ``display(Markdown(...))`` (or a bare
    ``Markdown(...)``) with a string or f-string, else None.
    """
    if not isinstance(statement, ast.Expr):
        return None
    call = statement.value
    if _call_name(call) == "display" and len(call.args) == 1 and not call.keywords:
        call = call.args[0]
    if _call_name(call) == "Markdown" and len(call.args) == 1 and not call.keywords:
        return fstring_template(call.args[0])
    return None


def show_displayed_markdown(
    text: str,
    where: str,
    notes: list[tuple[str, Note]],
    outputs: list[dict] | None = None,
    accounted: int = 0,
) -> list[str | Shown]:
    """
    Code lines, with each ``display(Markdown(f"..."))`` replaced by the
    Markdown as comment lines (``Shown``), its values filled by handcalcs
    (``{{ x }}``). Other output gets a warning: from the cell's saved
    ``outputs``, or, in a notebook saved without outputs, a last line that is
    a value (not a call).
    """
    lines: list[str | Shown] = list(text.splitlines())
    tree = ast.parse(text)
    replaced = 0
    for statement in reversed(tree.body):
        template = displayed_markdown(statement)
        if template is not None:
            shown = [Shown(l) for l in markdown_lines(template)]
            lines[statement.lineno - 1 : statement.end_lineno] = shown
            replaced += 1
    if outputs:
        shown_outputs = sum(
            o.get("output_type") in ("execute_result", "display_data", "stream")
            for o in outputs
        )
        # ``accounted``: outputs already explained (displaying @handcalc calls).
        other = shown_outputs > replaced + accounted
    else:
        last = tree.body[-1] if tree.body else None
        other = (
            isinstance(last, ast.Expr)
            and displayed_markdown(last) is None
            and isinstance(last.value, (ast.Name, ast.Attribute, ast.Subscript))
        )
    if replaced:
        notes.append(
            (
                where,
                change(
                    f"displayed Markdown is now comment lines, with its values in "
                    f"{{{{ }}}} ({replaced})"
                ),
            )
        )
    if other:
        notes.append(
            (
                where,
                warning(
                    "this cell shows output (display, print, or the value of "
                    "its last line) that the script won't: write it as a "
                    "comment or a calculation, or add it in your document"
                ),
            )
        )
    return lines


# --- The script ----------------------------------------------------------------


@dataclass
class Segment:
    kind: str  # "prose", "calc" or "code"
    lines: list[str | Shown]


def displaying_functions(texts: list[str]) -> set[str]:
    """The functions decorated with ``@handcalc(..., display=True)`` in ``texts``."""
    names = set()
    for text in texts:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and _call_name(decorator) == "handcalc"
                    and any(
                        k.arg == "display"
                        and isinstance(k.value, ast.Constant)
                        and k.value.value is True
                        for k in decorator.keywords
                    )
                ):
                    names.add(node.name)
    return names


def calls_displayed(statement: ast.stmt, functions: set[str]) -> bool:
    """A top-level ``x = f(...)`` (or ``f(...)``) calling a displaying ``@handcalc``."""
    if isinstance(statement, (ast.Assign, ast.Expr)):
        return _call_name(statement.value) in functions
    return False


def drop_display_decorators(
    text: str, functions: set[str], where: str, notes: list[tuple[str, Note]]
) -> str:
    """
    ``text`` without the ``@handcalc(..., display=True)`` decorators of
    ``functions``. A script can't show a function's working, and handcalcs
    can't read the source of a function in a script it runs; with
    ``display=True`` the function returned only its value, as it does
    undecorated.
    """
    tree = ast.parse(text)
    drop: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name in functions
        ):
            for decorator in node.decorator_list:
                if _call_name(decorator) == "handcalc":
                    drop.append((decorator.lineno, decorator.end_lineno))
    if not drop:
        return text
    lines = text.splitlines()
    for start, end in sorted(drop, reverse=True):
        del lines[start - 1 : end]
    notes.append(
        (
            where,
            change(
                f"'@handcalc(..., display=True)' removed ({len(drop)}): the "
                "script shows each call and its result"
            ),
        )
    )
    return "\n".join(lines)


def code_cell_lines(
    source: str,
    where: str,
    notes: list[tuple[str, Note]],
    functions: set[str] = frozenset(),
    outputs: list[dict] | None = None,
) -> list[str | Shown]:
    """
    A code cell that the notebook didn't render, as script lines: line magics
    and ``!`` commands dropped, a ``%render <line>`` kept as a ``Shown`` line,
    a non-Python cell magic commented out. A call to a ``@handcalc`` function
    that displayed its render (in ``functions``) is shown too: the script shows
    the call and its result, not the function's working. Empty when nothing
    is left.
    """
    magics, lines = cell_magics(source)
    if magics and magics[-1][0] in NON_PYTHON_CELL_MAGICS:
        name, args = magics[-1]
        return comment_out([f"%%{name} {args}".rstrip(), *lines])
    shown = set()
    for k, line in enumerate(lines):
        match = _RENDER_LINE_RE.match(line)
        if match:
            lines[k] = match.group(1) + match.group(2)
            shown.add(lines[k])
    text = strip_line_magics("\n".join(lines))
    if not text.strip():
        return []
    try:
        ast.parse(text)
    except SyntaxError as error:
        notes.append((where, warning(f"not valid Python ({error.msg}); commented out")))
        return comment_out(text.splitlines())
    text = drop_display_decorators(text, functions, where, notes)
    tree = ast.parse(text)
    for statement in tree.body:
        if calls_displayed(statement, functions):
            for number in range(statement.lineno, statement.end_lineno + 1):
                shown.add(text.splitlines()[number - 1])
    calls = sum(calls_displayed(st, functions) for st in tree.body)
    lines = show_displayed_markdown(text, where, notes, outputs, calls)
    return [Shown(l) if isinstance(l, str) and l in shown else l for l in lines]


def notebook_segments(
    notebook: dict[str, Any], notes: list[tuple[str, Note]]
) -> list[Segment]:
    segments: list[Segment] = []
    codes: list[str] = []
    first = True
    functions = displaying_functions(
        [
            cell_text(c)
            for c in notebook.get("cells", [])
            if c.get("cell_type") == "code"
        ]
    )
    if functions:
        notes.append(
            (
                "",
                warning(
                    f"@handcalc functions ({', '.join(sorted(functions))}): the "
                    "script shows each call and its result, not the function's "
                    "working; to show the working, write the calculation in a "
                    "%%render cell"
                ),
            )
        )
    for index, cell in enumerate(notebook.get("cells", [])):
        where = f"cell {index + 1}"
        text = cell_text(cell)
        if first and text.strip():
            stripped = strip_front_matter(text)
            if stripped != text:
                notes.append((where, change("front matter dropped")))
                text = stripped
            first = False
        kind = cell.get("cell_type")
        if kind == "markdown":
            images = _IMAGE_RE.findall(text)
            if images:
                text = _IMAGE_RE.sub("", text)
                notes.append(
                    (
                        where,
                        warning(
                            f"image(s) left out ({len(images)}): handcalcs doesn't "
                            "show images; add them in your document"
                        ),
                    )
                )
            lines = markdown_lines(text)
            if lines:
                segments.append(Segment("prose", lines))
        elif kind != "code":
            if text.strip():
                notes.append((where, change(f"{kind} cell dropped")))
        else:
            magics, body = cell_magics(text)
            render = [m for m in magics if m[0] in RENDER_MAGICS]
            if render:
                name, args = render[-1]
                if "inputs=" in args or "destination=" in args:
                    notes.append(
                        (
                            where,
                            warning(
                                f"'%%{name} {args}': its arguments don't apply to "
                                "a script; the cell is exported as it reads"
                            ),
                        )
                    )
                body_text = strip_line_magics("\n".join(body))
                lines = calc_lines(body_text.splitlines(), option_values(codes))
                segments.append(Segment("calc", lines))
                codes.append(body_text)
            else:
                lines = code_cell_lines(
                    text, where, notes, functions, cell.get("outputs")
                )
                if lines:
                    segments.append(Segment("code", lines))
                    codes.append(
                        "\n".join(l.line if isinstance(l, Shown) else l for l in lines)
                    )
    return segments


def assemble(segments: list[Segment], show_code: bool) -> str:
    """Join the segments; consecutive hidden code cells share one hidden block."""
    blocks: list[list[str]] = []
    hidden: list[str] = []

    def flush() -> None:
        if hidden:
            blocks.append([HIDE, *hidden_lines(hidden), SHOW])
            hidden.clear()

    for segment in segments:
        if segment.kind == "code" and not show_code:
            if hidden:
                hidden.append("")
            shown: list[str] = []
            for line in [*segment.lines, ""]:
                if isinstance(line, Shown):
                    shown.append(line.line)
                    continue
                if shown:
                    # What the notebook showed (%render, Markdown): show it.
                    hidden.extend([SHOW, *shown, HIDE])
                    shown = []
                hidden.append(line)
            hidden.pop()
            continue
        flush()
        blocks.append([l.line if isinstance(l, Shown) else l for l in segment.lines])
    flush()
    return "\n\n".join("\n".join(block) for block in blocks)


def normalize_whitespace(code: str) -> str:
    # A hidden block that hides nothing (e.g. after a shown last line).
    code = re.sub(
        rf"^{re.escape(HIDE)}\n(?:\s*\n)*{re.escape(SHOW)}$\n?", "", code, flags=re.M
    )
    lines = [line.rstrip() for line in code.splitlines()]
    code = "\n".join(lines).strip("\n")
    return _EXCESS_BLANKS_RE.sub("\n\n", code) + "\n"


def format_with_black(code: str, source_name: str = "<notebook>") -> str:
    try:
        import black
    except ImportError:
        log.warning("black is not installed; %s is left unformatted", source_name)
        return code
    try:
        return black.format_str(code, mode=black.Mode())
    except Exception as exc:  # black raises several exception types
        log.warning(
            "black could not format %s, leaving unformatted: %s", source_name, exc
        )
        return code


def export_notebook(
    raw: str | dict[str, Any], options: ExportOptions, name: str = "<notebook>"
) -> FileResult:
    """
    Export a notebook (its JSON text, or the parsed JSON, which is not
    changed) as a handcalcs v2 script. The result's text is the script; its
    notes say what was converted and what to check.
    """
    notebook = json.loads(raw if isinstance(raw, str) else json.dumps(raw))
    result = migrate_notebook(notebook, options)
    notes = list(result.notes)
    segments = notebook_segments(notebook, notes)
    script = normalize_whitespace(assemble(segments, options.show_code))
    try:
        ast.parse(script)
    except SyntaxError as error:
        raise ValueError(f"the exported script doesn't parse: {error}") from None
    if options.black:
        script = format_with_black(script, name)
    return FileResult(script, notes, uses_handcalcs=result.uses_handcalcs)

"""
Converting handcalcs v1 source to handcalcs v2.

Two kinds of source are converted:

- a ``%%render`` (or ``%%tex``) cell: its v1 arguments (``params``, ``long``,
  ``symbolic``, a precision, ``sci_not``) become v2 comment commands, and its v1
  comment conventions become v2 ones (see ``migrate_calc_lines``);
- any other Python (a code cell or a ``.py`` file): imports, ``@handcalc``
  decorators, ``set_option`` calls and the line magics that changed.

Source is edited in place, as text: only what changes is rewritten, so the
rest keeps its formatting and comments. Each change, and each thing that needs
a person to look at it, is recorded as a ``Note``.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass, field

TOOL = "handcalcs-migrate"
GUIDE = "https://handcalcs.structuralpython.com/getting-started/migrating-from-v1.html"


@dataclass(frozen=True)
class Note:
    """A change made (``change``) or something to check by hand (``warning``)."""

    level: str  # "change" or "warning"
    message: str
    line: int | None = None  # 1-based, in the converted cell or file

    def __str__(self) -> str:
        where = f"line {self.line}: " if self.line else ""
        return f"{where}{self.message}"


@dataclass
class Options:
    # Add ``-f .3f`` where v1 used its default precision (3 decimal places).
    keep_v1_precision: bool = False


@dataclass
class Result:
    source: str
    notes: list[Note] = field(default_factory=list)
    # A v1 decorator was converted here and needs ``LatexRenderer`` imported.
    needs_latex_renderer: bool = False

    @property
    def changed(self) -> bool:
        return any(note.level == "change" for note in self.notes)


def change(message: str, line: int | None = None) -> Note:
    return Note("change", message, line)


def warning(message: str, line: int | None = None) -> Note:
    return Note("warning", message, line)


# --- v1 %%render arguments ---------------------------------------------------

# The order v1 tried them in (render.parse_line_args).
V1_OVERRIDES = ("params", "long", "short", "sympy", "symbolic", "_testing")


@dataclass
class RenderArgs:
    override: str = ""
    precision: int | None = None
    sympy: bool = False
    sci_not: bool = False
    # Arguments v1 matched loosely (``param`` -> ``params``), as (given, meant).
    loose: list[tuple[str, str]] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)


def parse_render_args(line: str) -> RenderArgs:
    """
    The arguments of a v1 ``%%render``/``%%tex`` line, read as v1 read them: an
    argument selects the first override it is part of (``long``, but also
    ``lon`` or ``s``), an integer is the precision, ``sympy`` and ``sci_not``
    are flags.
    """
    args = RenderArgs()
    for arg in line.split():
        lower = arg.lower()
        if lower == "sympy":
            args.sympy = True
            continue
        if lower == "sci_not":
            args.sci_not = True
            continue
        try:
            args.precision = int(arg)
            continue
        except ValueError:
            pass
        meant = next((valid for valid in V1_OVERRIDES if lower in valid), None)
        if meant is None:
            args.unknown.append(arg)
            continue
        if meant == "sympy":
            args.sympy = True
            continue
        if lower != meant:
            args.loose.append((arg, meant))
        args.override = meant
    return args


def format_code(
    precision: int | None, scientific: bool, options: Options
) -> str | None:
    """The v2 format code for a v1 precision (decimal places) and notation."""
    if precision is None and not scientific and not options.keep_v1_precision:
        return None
    digits = 3 if precision is None else precision
    return f".{digits}{'e' if scientific else 'f'}"


# --- Comments and lines ------------------------------------------------------


def string_lines(text: str) -> set[int]:
    """The 1-based lines of ``text`` that start inside a multi-line string."""
    inside: set[int] = set()
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.STRING and token.end[0] > token.start[0]:
                inside.update(range(token.start[0] + 1, token.end[0] + 1))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return inside


def split_comment(line: str) -> tuple[str, str | None]:
    """``line`` as (code, comment text without ``#``), or (line, None)."""
    quote = None
    i = 0
    while i < len(line):
        char = line[i]
        if quote:
            if char == "\\":
                i += 2
                continue
            if line.startswith(quote, i):
                i += len(quote)
                quote = None
                continue
        elif char in "\"'":
            quote = char * 3 if line.startswith(char * 3, i) else char
            i += len(quote)
            continue
        elif char == "#":
            return line[:i], line[i + 1 :].rstrip("\r\n")
        i += 1
    return line, None


def is_v2_command(stripped: str) -> bool:
    return bool(re.match(r"#\s*hc\s*:", stripped))


def line_ending(line: str) -> str:
    return line[len(line.rstrip("\r\n")) :] or "\n"


def assignment_run_starts(text: str, statements: list[ast.stmt] | None) -> set[int]:
    """
    The 1-based lines of ``text`` that start a run of assignments: what v2's
    ``# hc: -g`` collapses into a grid. A run ends at a statement that isn't an
    assignment, a blank line or a comment line, as it does in v2.
    """
    lines = text.splitlines()
    if statements is None:
        try:
            statements = ast.parse(text).body
        except SyntaxError:
            # Not Python as a whole: one assignment per line, at the margin.
            simple = re.compile(r"[A-Za-z_][\w.]*(\s*,\s*[A-Za-z_][\w.]*)*\s*=(?!=)")
            starts, previous = set(), False
            for number, line in enumerate(lines, 1):
                is_assignment = bool(simple.match(line))
                if is_assignment and not previous:
                    starts.add(number)
                previous = is_assignment
            return starts
    starts: set[int] = set()
    previous: ast.stmt | None = None
    for statement in statements:
        if isinstance(statement, ast.Assign):
            gap = previous is None or not isinstance(previous, ast.Assign)
            if not gap:
                between = lines[previous.end_lineno : statement.lineno - 1]
                gap = any(not l.strip() or l.strip().startswith("#") for l in between)
            if gap:
                starts.add(statement.lineno)
        previous = statement
    return starts


def migrate_calc_lines(
    lines: list[str],
    first_line: int,
    params: bool,
    notes: list[Note],
    statements: list[ast.stmt] | None = None,
) -> list[str]:
    """
    Convert the lines of a v1 calculation (a ``%%render`` cell's body, or a
    decorated function's body) to v2 conventions. ``first_line`` is the
    1-based number of ``lines[0]`` in the output, for the notes.

    - ``## text`` was text between the equations in v1; in v2 ``##`` is a
      heading, so it becomes ``# text`` (a paragraph).
    - A line that is only a ``# comment`` was not shown in v1; in v2 it would
      be, so a run of them is wrapped in ``# hc: -i`` / ``# hc: -s``.
    - A line ending in ``ignore`` (``x = 1  # ignore``) was hidden in v1; it
      gets v2's ``# hc: -i``.
    - With ``params`` (a v1 ``%%render params`` cell), each run of assignments
      gets v2's ``# hc: -g``, which shows it as a parameter grid.
    """
    text = "".join(lines)
    in_string = string_lines(text)
    run_starts = assignment_run_starts(text, statements) if params else set()
    out: list[str] = []
    intertext = hidden = ignored = 0
    i = 0
    while i < len(lines):
        number = i + 1
        line = lines[i]
        stripped = line.strip()
        indent = line[: len(line) - len(line.lstrip())]
        # A rewritten line keeps its own ending (the last line has none); an
        # added line takes the ending of the line it is added before.
        own_end = line[len(line.rstrip("\r\n")) :]
        end = line_ending(line)
        if number in in_string or not stripped:
            out.append(line)
        elif stripped.startswith("##"):
            out.append(f"{indent}# {stripped.lstrip('#').strip()}{own_end}")
            intertext += 1
        elif stripped.startswith("#") and not is_v2_command(stripped):
            j = i
            while j < len(lines) and (j + 1) not in in_string:
                s = lines[j].strip()
                if not s.startswith("#") or s.startswith("##") or is_v2_command(s):
                    break
                j += 1
            out.append(f"{indent}# hc: -i{end}")
            block = lines[i:j]
            if not block[-1].endswith(("\n", "\r")):
                block[-1] += end
            out.extend(block)
            out.append(
                f"{indent}# hc: -s{line_ending(lines[j - 1]) if j < len(lines) else ''}"
            )
            hidden += j - i
            i = j
            continue
        else:
            if number in run_starts:
                out.append(f"{indent}# hc: -g{end}")
            code, comment = split_comment(line.rstrip("\r\n"))
            if line.rstrip().endswith("ignore") and (
                comment is None or comment.strip().lower().endswith("ignore")
            ):
                out.append(f"{code.rstrip()}  # hc: -i{own_end}")
                ignored += 1
            else:
                out.append(line)
        i += 1
    if intertext:
        notes.append(
            change(
                f"'## text' between equations is now '# text' ({intertext} "
                "line(s)): in v2 '##' is a heading",
                first_line,
            )
        )
    if hidden:
        notes.append(
            change(
                f"comment lines that v1 didn't show are wrapped in "
                f"'# hc: -i' / '# hc: -s' ({hidden} line(s))",
                first_line,
            )
        )
    if ignored:
        notes.append(
            change(f"'# ignore' lines now use '# hc: -i' ({ignored})", first_line)
        )
    if run_starts:
        notes.append(
            change(
                "'params': each run of assignments starts with '# hc: -g' "
                "(a parameter grid)",
                first_line,
            )
        )
    return out


# --- %%render cells ----------------------------------------------------------


def is_render_cell(source: str) -> bool:
    first = source.lstrip("﻿").split("\n", 1)[0].strip()
    return bool(re.match(r"%%(render|tex)\b", first))


def convert_render_cell(source: str, options: Options) -> Result:
    """Convert a v1 ``%%render``/``%%tex`` cell to a v2 ``%%render`` cell."""
    lines = source.splitlines(keepends=True)
    magic, *rest = lines[0].strip().split(None, 1)
    args = parse_render_args(rest[0] if rest else "")
    end = line_ending(lines[0]) if len(lines) > 1 else "\n"
    notes: list[Note] = []

    header = ["%%render" + end]
    if magic == "%%tex":
        notes.append(
            warning(
                "'%%tex' printed the LaTeX source in v1. It is now '%%render'; to "
                "get LaTeX, run '%hc_default_renderer latex' in an earlier cell, "
                "or render with HandCalcs(LatexRenderer())",
                1,
            )
        )
    commands = []
    if args.override == "long":
        commands.append("-m")
    code = format_code(args.precision, args.sci_not, options)
    if code:
        commands.append(f"-f {code}")
    if commands:
        header.append(f"# hc: {' '.join(commands)}{end}")
    if args.override == "symbolic":
        header.append(f'# hc: mode = "ass sym"{end}')
    given = (rest[0] if rest else "").strip()
    if given or magic == "%%tex":
        old = f"{magic} {given}".strip()
        new = "%%render" + "".join(f" + '{l.strip()}'" for l in header[1:])
        notes.append(change(f"'{old}' -> {new}", 1))
    for arg, meant in args.loose:
        notes.append(warning(f"v1 read the argument '{arg}' as '{meant}'", 1))
    for arg in args.unknown:
        notes.append(warning(f"v1 ignored the argument '{arg}'; it is dropped", 1))
    if args.sympy:
        notes.append(
            warning(
                "'sympy' cells are not supported by handcalcs 2.0: rewrite this "
                "cell as plain Python",
                1,
            )
        )
    if args.override == "short":
        notes.append(change("'short' is the default in v2: no command needed", 1))

    body = lines[1:]
    converted = migrate_calc_lines(
        body, len(header) + 1, args.override == "params", notes
    )
    return Result("".join(header + converted), notes)


# --- Python: imports, decorators, set_option -----------------------------------

# v1 modules that no longer exist, and what replaces them.
V1_MODULES = {
    "handcalcs.render": "handcalcs",
    "handcalcs.decorator": "handcalcs",
    "handcalcs.global_config": "handcalcs",
}
V1_INTERNAL = ("handcalcs.handcalcs", "handcalcs.sympy_kit", "handcalcs.integrations")

# v1 options and their v2 replacements (None: removed).
V1_OPTIONS_REMOVED = {
    "decimal_separator": "removed in v2",
    "latex_block_start": "now a renderer class attribute",
    "latex_block_end": "now a renderer class attribute",
    "math_environment_start": "now a renderer class attribute",
    "math_environment_end": "now a renderer class attribute",
    "line_break": "now a renderer class attribute",
    "preferred_string_formatter": "removed in v2",
    "underscore_subscripts": "removed: '_' always makes a subscript in v2",
    "greek_exclusions": "removed: see the 'greek_prefixes' option or 'symbols'",
    "custom_symbols": (
        "replaced by the 'symbols' option, which takes renderer-neutral specs "
        "for whole names (not LaTeX for parts of names)"
    ),
    "custom_brackets": "not available in v2: index the value or use 'symbols'",
}

V1_DECORATOR_PARAMS = (
    "override",
    "precision",
    "left",
    "right",
    "scientific_notation",
    "jupyter_display",
    "record",
)

MAGIC_LINE = re.compile(r"^(\s*)([%!])")


class Edits:
    """Text replacements by (line, column) position, applied together."""

    def __init__(self, text: str):
        self.text = text
        self.lines = text.splitlines(keepends=True)
        self.starts = [0]
        for line in self.lines:
            self.starts.append(self.starts[-1] + len(line))
        self.edits: list[tuple[int, int, str]] = []

    def index(self, lineno: int, col: int) -> int:
        """The index in the text of an ast (line, UTF-8 byte column)."""
        if lineno > len(self.lines):
            return len(self.text)
        line = self.lines[lineno - 1]
        return self.starts[lineno - 1] + len(
            line.encode("utf-8")[:col].decode("utf-8", errors="ignore")
        )

    def node_span(self, node: ast.AST) -> tuple[int, int]:
        return (
            self.index(node.lineno, node.col_offset),
            self.index(node.end_lineno, node.end_col_offset),
        )

    def line_span(self, first: int, last: int) -> tuple[int, int]:
        """Whole lines ``first`` to ``last`` (1-based, inclusive)."""
        return self.starts[first - 1], self.starts[min(last, len(self.lines))]

    def replace(self, start: int, end: int, text: str) -> None:
        self.edits.append((start, end, text))

    def apply(self) -> str:
        text = self.text
        last = len(text) + 1
        for start, end, replacement in sorted(self.edits, reverse=True):
            if end > last:
                continue  # overlaps a later edit; keep the later one
            text = text[:start] + replacement + text[end:]
            last = start
        return text


def masked(text: str) -> str:
    """``text`` with IPython magic and shell lines made into ``pass``."""
    out = []
    for line in text.splitlines(keepends=True):
        match = MAGIC_LINE.match(line)
        if match:
            out.append(f"{match.group(1)}pass{line_ending(line)}")
        else:
            out.append(line)
    return "".join(out)


@dataclass
class Names:
    """What the handcalcs names are in a notebook or file."""

    modules: set[str] = field(default_factory=lambda: {"handcalcs"})
    decorators: set[str] = field(default_factory=lambda: {"handcalc"})
    set_options: set[str] = field(default_factory=set)
    # Functions decorated with a v1 @handcalc that returns (latex, value).
    swapped_returns: set[str] = field(default_factory=set)


def scan_names(text: str, names: Names) -> None:
    """Add the handcalcs names that ``text`` binds or decorates to ``names``."""
    try:
        tree = ast.parse(masked(text))
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "handcalcs":
                    names.modules.add(alias.asname or "handcalcs")
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "handcalcs"
        ):
            for alias in node.names:
                if alias.name == "handcalc":
                    names.decorators.add(alias.asname or "handcalc")
                elif alias.name == "set_option":
                    names.set_options.add(alias.asname or "set_option")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                call = decorator_call(decorator, names)
                if call is not False and not v1_returns_value_only(call):
                    names.swapped_returns.add(node.name)


def is_handcalc_name(node: ast.expr, names: Names) -> bool:
    if isinstance(node, ast.Name):
        return node.id in names.decorators
    if isinstance(node, ast.Attribute) and node.attr == "handcalc":
        base = node.value
        while isinstance(base, ast.Attribute):
            base = base.value
        return isinstance(base, ast.Name) and base.id in names.modules
    return False


def decorator_call(decorator: ast.expr, names: Names):
    """The v1 ``@handcalc(...)`` call (None for a bare ``@handcalc``), or False."""
    if isinstance(decorator, ast.Call) and is_handcalc_name(decorator.func, names):
        return decorator
    if is_handcalc_name(decorator, names):
        return None
    return False


def v1_arguments(call: ast.Call | None) -> dict[str, ast.expr]:
    if call is None:
        return {}
    arguments = dict(zip(V1_DECORATOR_PARAMS, call.args))
    arguments.update({k.arg: k.value for k in call.keywords if k.arg})
    return arguments


def literal(node: ast.expr | None, default=None):
    if node is None:
        return default
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return ...


def v1_returns_value_only(call: ast.Call | None) -> bool:
    return literal(v1_arguments(call).get("jupyter_display"), False) is True


def is_v2_call(call: ast.Call | None) -> bool:
    """A decorator call already written for v2 (a renderer, or v2 keywords)."""
    if call is None:
        return False
    v2_keywords = {"render_context", "destination", "docstring", "display"}
    if any(k.arg in v2_keywords for k in call.keywords):
        return True
    return bool(call.args) and not isinstance(call.args[0], ast.Constant)


def convert_decorator(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    call: ast.Call | None,
    options: Options,
    notes: list[Note],
) -> tuple[str, list[str]]:
    """
    The v2 arguments for a v1 ``@handcalc(...)``, and the v1 override. v1
    rendered LaTeX, left out the docstring and returned ``(latex, value)``.
    """
    arguments = v1_arguments(call)
    line = (call or function).lineno
    values = {name: literal(node) for name, node in arguments.items()}
    for name, value in values.items():
        if value is ...:
            notes.append(
                warning(
                    f"@handcalc argument '{name}' isn't a literal; it was dropped, "
                    "so check the converted decorator",
                    line,
                )
            )
    override = values.get("override") if isinstance(values.get("override"), str) else ""
    precision = values.get("precision")
    precision = precision if isinstance(precision, int) else None
    scientific = values.get("scientific_notation") is True
    context: dict[str, object] = {}
    code = format_code(precision, scientific, options)
    if code:
        context["format_code"] = code
    if override == "long":
        context["multiline"] = True
    elif override == "params":
        context["param_line"] = True
    elif override == "symbolic":
        context["mode"] = "ass sym"
    parts = ["LatexRenderer()"]
    if context:
        items = ", ".join(f"{k!r}: {v!r}" for k, v in context.items())
        parts.append(f"render_context={{{items}}}".replace("'", '"'))
    if values.get("jupyter_display") is True:
        parts.append("display=True")
    if ast.get_docstring(function, clean=False) is not None:
        parts.append("docstring=False")
    for name in ("left", "right"):
        if values.get(name) not in (None, "", ...):
            notes.append(
                warning(
                    f"@handcalc '{name}={values[name]!r}' has no v2 equivalent and "
                    "was dropped: add the text around the render yourself",
                    line,
                )
            )
    if values.get("record") is True:
        notes.append(
            warning(
                "@handcalc 'record=True' (the call recorder) is not available in "
                "v2 and was dropped",
                line,
            )
        )
    return override, parts


def convert_python(text: str, names: Names, options: Options) -> Result:
    """Convert the Python in a code cell or ``.py`` file."""
    notes: list[Note] = []
    edits = Edits(text)
    result = Result(text, notes)
    lines = edits.lines

    # Magic lines, which aren't Python: handled by text.
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        start, end = edits.line_span(number, number)
        indent = line[: len(line) - len(line.lstrip())]
        if re.match(r"%load_ext\s+handcalcs(\.render)?\s*$", stripped):
            edits.replace(start, end, f"{indent}import handcalcs{line_ending(line)}")
            notes.append(
                change("'%load_ext handcalcs.render' -> 'import handcalcs'", number)
            )
        elif stripped.startswith("%decimal_separator"):
            edits.replace(
                start,
                end,
                f"{indent}# {stripped}  # {TOOL}: removed in handcalcs v2{line_ending(line)}",
            )
            notes.append(
                warning(
                    "'%decimal_separator' was removed in v2 and is commented out",
                    number,
                )
            )

    try:
        tree = ast.parse(masked(text))
    except SyntaxError as error:
        notes.append(
            warning(f"not valid Python ({error.msg}); only magic lines were converted")
        )
        result.source = edits.apply()
        return result

    convert_imports(tree, edits, notes)
    convert_set_options(tree, edits, names, notes)
    convert_decorators(tree, edits, names, options, result)
    swap_unpacked_returns(tree, edits, names, notes)
    result.source = edits.apply()
    return result


def convert_imports(tree: ast.Module, edits: Edits, notes: list[Note]) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            parts, changed = [], False
            for alias in node.names:
                name = V1_MODULES.get(alias.name, alias.name)
                changed |= name != alias.name
                asname = alias.asname
                if name == "handcalcs" and alias.name != "handcalcs" and asname:
                    text = f"handcalcs as {asname}"
                else:
                    text = name if not asname else f"{name} as {asname}"
                if text not in parts:
                    parts.append(text)
                if alias.name in V1_INTERNAL:
                    notes.append(
                        warning(f"'{alias.name}' is a v1 internal module", node.lineno)
                    )
            if changed:
                edits.replace(*edits.node_span(node), "import " + ", ".join(parts))
                notes.append(
                    change("import of a v1 module -> 'import handcalcs'", node.lineno)
                )
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            module = node.module or ""
            if module in V1_INTERNAL or module.startswith(V1_INTERNAL):
                notes.append(
                    warning(
                        f"'from {module} import ...' uses v1 internals, which v2 "
                        "doesn't have",
                        node.lineno,
                    )
                )
                continue
            if module in V1_MODULES:
                names_text = ", ".join(
                    a.name if not a.asname else f"{a.name} as {a.asname}"
                    for a in node.names
                )
                edits.replace(
                    *edits.node_span(node), f"from handcalcs import {names_text}"
                )
                notes.append(
                    change(
                        f"'from {module} import' -> 'from handcalcs import'",
                        node.lineno,
                    )
                )
            elif module == "handcalcs" and any(a.name == "render" for a in node.names):
                kept = [
                    a.name if not a.asname else f"{a.name} as {a.asname}"
                    for a in node.names
                    if a.name != "render"
                ]
                text = "import handcalcs"
                if kept:
                    text = f"from handcalcs import {', '.join(kept)}\nimport handcalcs"
                edits.replace(*edits.node_span(node), text)
                notes.append(
                    change(
                        "'from handcalcs import render' -> 'import handcalcs'",
                        node.lineno,
                    )
                )


def convert_set_options(
    tree: ast.Module, edits: Edits, names: Names, notes: list[Note]
) -> None:
    for statement in ast.walk(tree):
        if not (
            isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
        ):
            continue
        call = statement.value
        func = call.func
        is_set_option = (
            isinstance(func, ast.Attribute)
            and func.attr == "set_option"
            and isinstance(func.value, ast.Name)
            and func.value.id in names.modules
        ) or (isinstance(func, ast.Name) and func.id in names.set_options)
        if not is_set_option or len(call.args) != 2:
            continue
        option = literal(call.args[0])
        value = literal(call.args[1])
        func_text = ast.get_source_segment(edits.text, func) or "handcalcs.set_option"
        line = statement.lineno
        if option == "display_precision" and isinstance(value, int):
            new = f'{func_text}("format_code", ".{value}f")'
            edits.replace(*edits.node_span(call), new)
            notes.append(
                change(
                    f"set_option('display_precision', {value}) -> 'format_code'", line
                )
            )
        elif option == "use_scientific_notation" and value is True:
            new = f'{func_text}("format_code", ".3e")'
            edits.replace(*edits.node_span(call), new)
            notes.append(
                warning(
                    "set_option('use_scientific_notation', True) -> format_code "
                    "'.3e': check the number of digits (v1 used display_precision)",
                    line,
                )
            )
        elif option == "param_columns" and isinstance(value, int):
            new = f'{func_text}("param_cols", {value})'
            edits.replace(*edits.node_span(call), new)
            notes.append(
                change(f"set_option('param_columns', {value}) -> 'param_cols'", line)
            )
        elif option == "use_scientific_notation" or option in V1_OPTIONS_REMOVED:
            reason = V1_OPTIONS_REMOVED.get(option, "removed in v2")
            start, end = edits.line_span(statement.lineno, statement.end_lineno)
            block = edits.text[start:end]
            indent = block[: len(block) - len(block.lstrip())]
            commented = "".join(
                f"{indent}# {l[len(indent):]}" if l.strip() else l
                for l in block.splitlines(keepends=True)
            )
            edits.replace(
                start,
                end,
                f"{indent}# {TOOL}: the v1 option '{option}' is {reason}\n{commented}",
            )
            notes.append(
                warning(f"the v1 option '{option}' is {reason}; commented out", line)
            )


def body_start(
    function: ast.FunctionDef | ast.AsyncFunctionDef, lines: list[str]
) -> int:
    """
    The first line (1-based) of a function's body: its first statement, or the
    comment lines directly above it (v2 renders those as part of the body).
    """
    first = function.body[0].lineno
    while first - 1 > function.lineno and lines[first - 2].strip().startswith("#"):
        first -= 1
    return first


def convert_decorators(
    tree: ast.Module, edits: Edits, names: Names, options: Options, result: Result
) -> None:
    notes = result.notes
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in function.decorator_list:
            call = decorator_call(decorator, names)
            if call is False:
                continue
            if is_v2_call(call):
                break
            override, parts = convert_decorator(function, call, options, notes)
            func_text = ast.get_source_segment(
                edits.text, call.func if call is not None else decorator
            )
            edits.replace(
                *edits.node_span(decorator), f"{func_text}({', '.join(parts)})"
            )
            result.needs_latex_renderer = True
            notes.append(
                change(
                    f"@handcalc on '{function.name}' -> v2: renders LaTeX, "
                    + (
                        "shows the render"
                        if "display=True" in parts
                        else "returns (value, latex)"
                    ),
                    decorator.lineno,
                )
            )
            if function.body[0].lineno > function.lineno:
                first = body_start(function, edits.lines)
                last = function.end_lineno
                start, end = edits.line_span(first, last)
                body = edits.lines[first - 1 : last]
                body_notes: list[Note] = []
                # v1's 'params' showed each line as a parameter; v2's
                # render_context param_line does that, so no grid is added.
                converted = migrate_calc_lines(body, first, False, body_notes)
                if converted != body:
                    edits.replace(start, end, "".join(converted))
                    notes.extend(body_notes)
            break


def swap_unpacked_returns(
    tree: ast.Module, edits: Edits, names: Names, notes: list[Note]
) -> None:
    """
    v1's decorated functions returned ``(latex, value)``; v2's return
    ``(value, latex)``. Swap ``latex, value = f(...)``; flag other calls.
    """
    if not names.swapped_returns:
        return
    handled: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], (ast.Tuple, ast.List))
            and len(node.targets[0].elts) == 2
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id in names.swapped_returns
        ):
            first, second = node.targets[0].elts
            first_text = ast.get_source_segment(edits.text, first)
            second_text = ast.get_source_segment(edits.text, second)
            edits.replace(*edits.node_span(first), second_text)
            edits.replace(*edits.node_span(second), first_text)
            handled.add(id(node.value))
            notes.append(
                change(
                    f"'{first_text}, {second_text} = {node.value.func.id}(...)' -> "
                    f"'{second_text}, {first_text} = ...': v2 returns (value, latex)",
                    node.lineno,
                )
            )
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in names.swapped_returns
            and id(node) not in handled
        ):
            notes.append(
                warning(
                    f"'{node.func.id}(...)' returned (latex, value) in v1 and "
                    "returns (value, latex) in v2: check how its result is used",
                    node.lineno,
                )
            )

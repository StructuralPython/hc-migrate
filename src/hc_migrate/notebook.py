"""
Converting whole notebooks and ``.py`` files.

A notebook is read and written as JSON with the standard library, keeping its
cells, outputs and metadata as they are; only the source of converted code
cells changes.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Any

from .detect import source_version
from .convert import (
    Names,
    Note,
    Options as ConvertOptions,
    change,
    warning,
    convert_python,
    convert_render_cell,
    is_render_cell,
    masked,
    scan_names,
)

LATEX_IMPORT = "from handcalcs.renderers import LatexRenderer"
# v1 named things differently; these options give the v1 look in v2.
V1_NAME_OPTIONS = (
    'handcalcs.set_option("subscripts", "nested")',
    'handcalcs.set_option("greek_prefixes", False)',
)


@dataclass
class Options(ConvertOptions):
    # Add set_option calls that keep v1's subscripts and Greek names.
    v1_names: bool = False
    # Clear the outputs of the cells that were converted.
    clear_outputs: bool = False
    # Which handcalcs the source was written for: "v1" (convert it), "v2"
    # (leave it) or "auto" (tell from the source, see ``detect``; v2 when
    # nothing tells).
    source: str = "v1"


@dataclass
class FileResult:
    """The converted text of a file, and its notes by location."""

    text: str
    notes: list[tuple[str, Note]] = field(default_factory=list)
    uses_handcalcs: bool = False

    @property
    def changed(self) -> bool:
        return any(note.level == "change" for _, note in self.notes)

    @property
    def warnings(self) -> list[tuple[str, Note]]:
        return [(where, note) for where, note in self.notes if note.level == "warning"]


def uses_handcalcs(text: str) -> bool:
    return "handcalc" in text or bool(re.search(r"^%%(render|tex)\b", text, re.M))


def cell_text(cell: dict) -> str:
    source = cell.get("source", "")
    return "".join(source) if isinstance(source, list) else source


def set_cell_text(cell: dict, text: str) -> None:
    if isinstance(cell.get("source"), list):
        cell["source"] = text.splitlines(keepends=True)
    else:
        cell["source"] = text


def handcalcs_import_line(text: str) -> int | None:
    """The last line (1-based) of the first handcalcs import in ``text``."""
    try:
        tree = ast.parse(masked(text))
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.Import) and any(
            a.name.split(".")[0] == "handcalcs" for a in node.names
        ):
            return node.end_lineno
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == (
            "handcalcs"
        ):
            return node.end_lineno
    return None


def insert_after(text: str, line: int, new_lines: list[str]) -> str:
    lines = text.splitlines(keepends=True)
    head = lines[:line]
    if head and not head[-1].endswith("\n"):
        head[-1] += "\n"
    tail = lines[line:]
    block = "".join(f"{l}\n" for l in new_lines)
    if not tail:
        block = block.rstrip("\n")
    return "".join(head) + block + "".join(tail)


def binds_name(texts: list[str], name: str) -> bool:
    return any(re.search(rf"\b{name}\b", text) for text in texts)


def add_imports(
    texts: list[str], where: list[str], needs_latex: bool, options: Options
) -> tuple[list[str], list[tuple[str, Note]]]:
    """
    Add what converted code needs after the first handcalcs import (or at the
    top of the first converted source): ``LatexRenderer`` for converted
    decorators, and the v1-names options.
    """
    notes: list[tuple[str, Note]] = []
    additions = []
    if needs_latex and not binds_name(texts, r"import[^\n]*LatexRenderer"):
        additions.append(LATEX_IMPORT)
    if options.v1_names:
        if not binds_name(texts, r"import handcalcs"):
            additions.append("import handcalcs")
        additions.extend(V1_NAME_OPTIONS)
    if not additions:
        return texts, notes
    for index, text in enumerate(texts):
        line = handcalcs_import_line(text)
        if line is not None:
            break
    else:
        # No handcalcs import (it is in a file this one runs, say): add them
        # at the top of the first source that uses what they provide.
        index = next(
            (
                k
                for k, t in enumerate(texts)
                if "LatexRenderer()" in t or uses_handcalcs(t)
            ),
            0,
        )
        line = 0
    texts[index] = insert_after(texts[index], line, additions)
    for added in additions:
        notes.append((where[index], change(f"added '{added}'", line + 1)))
    return texts, notes


def resolve_source(texts: list[str], options: Options) -> tuple[str, list[Note]]:
    """
    The handcalcs version the source was written for (``options.source``, or
    detected for "auto"), and a note when it could not be told.
    """
    if options.source != "auto":
        return options.source, []
    found = source_version(texts)
    if found:
        return found, []
    return "v2", [
        warning(
            "could not tell whether this was written for handcalcs v1 or v2; "
            "treated as v2 (use --from v1 to convert it from v1)"
        )
    ]


def convert_notebook(raw: str, options: Options) -> FileResult:
    """Convert a notebook's JSON text."""
    notebook: dict[str, Any] = json.loads(raw)
    result = migrate_notebook(notebook, options)
    result.text = raw
    if result.changed:
        indent = (
            1 if re.match(r'\{\n "', raw) else (2 if re.match(r'\{\n  "', raw) else 1)
        )
        result.text = json.dumps(notebook, indent=indent, ensure_ascii=False) + "\n"
    return result


def migrate_notebook(notebook: dict[str, Any], options: Options) -> FileResult:
    """
    Convert a notebook (its parsed JSON) from v1 to v2 in place. The result's
    text is empty; its notes say what changed.
    """
    cells = notebook.get("cells", [])
    code = [(i, c) for i, c in enumerate(cells) if c.get("cell_type") == "code"]
    texts = {i: cell_text(c) for i, c in code}
    result = FileResult(
        "", uses_handcalcs=any(uses_handcalcs(t) for t in texts.values())
    )
    if not result.uses_handcalcs:
        return result
    version, notes = resolve_source(list(texts.values()), options)
    result.notes.extend(("", note) for note in notes)
    if version != "v1":
        return result

    names = Names()
    for text in texts.values():
        if not is_render_cell(text):
            scan_names(text, names)

    converted: dict[int, str] = {}
    needs_latex = False
    for index, cell in code:
        text = texts[index]
        where = f"cell {index + 1}"
        if is_render_cell(text):
            cell_result = convert_render_cell(text, options)
        elif text.lstrip().startswith("%%"):
            # Another cell magic (%%bash, %%timeit, ...): not handcalcs.
            converted[index] = text
            continue
        else:
            cell_result = convert_python(text, names, options)
            needs_latex |= cell_result.needs_latex_renderer
        result.notes.extend((where, note) for note in cell_result.notes)
        converted[index] = cell_result.source

    order = [i for i, _ in code]
    new_texts, notes = add_imports(
        [converted[i] for i in order],
        [f"cell {i + 1}" for i in order],
        needs_latex,
        options,
    )
    result.notes.extend(notes)
    for k, index in enumerate(order):
        if new_texts[k] != texts[index]:
            cell = cells[index]
            set_cell_text(cell, new_texts[k])
            if options.clear_outputs:
                cell["outputs"] = []
                cell["execution_count"] = None
    return result


def convert_script(text: str, options: Options) -> FileResult:
    """Convert a ``.py`` file."""
    result = FileResult(text, uses_handcalcs=uses_handcalcs(text))
    if not result.uses_handcalcs:
        return result
    version, notes = resolve_source([text], options)
    result.notes.extend(("", note) for note in notes)
    if version != "v1":
        return result
    names = Names()
    scan_names(text, names)
    converted = convert_python(text, names, options)
    result.notes.extend(("", note) for note in converted.notes)
    texts, notes = add_imports(
        [converted.source], [""], converted.needs_latex_renderer, options
    )
    result.notes.extend(notes)
    result.text = texts[0]
    return result

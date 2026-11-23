"""
Telling a notebook or script written for handcalcs v1 from one written for v2.

A v1 notebook has to load v1's ``%%render`` (``import handcalcs.render`` or
``%load_ext handcalcs.render``), so its imports nearly always give it away. The
other v1 signs are v1's ``%%render`` arguments, ``%%tex``, the v1 ``@handcalc``
keywords and the v1 options. v2 signs are ``# hc:`` comment commands, a plain
``import handcalcs`` with ``%%render`` (v1 needed ``handcalcs.render``),
``%%source`` and the v2 decorator keywords.
"""

from __future__ import annotations

import re

from .convert import V1_OVERRIDES

V1_PATTERNS = (
    # Imports and the extension.
    r"^\s*(?:import|from)\s+handcalcs\.(?:render|decorator|global_config)\b",
    r"^\s*from\s+handcalcs\s+import\s+render\b",
    r"^\s*%load_ext\s+handcalcs\.render\b",
    r"^\s*%%tex\b",
    # v1 @handcalc keywords.
    r"^\s*@handcalc\([^)]*\b(?:override|precision|left|right|jupyter_display|record)\s*=",
    # v1 options (not in a comment: a converted file comments out the ones
    # v2 removed).
    r"^[^#\n]*set_option\(\s*['\"](?:display_precision|param_columns|latex_block_start|"
    r"latex_block_end|math_environment_start|math_environment_end|line_break|"
    r"custom_symbols|custom_brackets|greek_exclusions|underscore_subscripts|"
    r"preferred_string_formatter|decimal_separator)['\"]",
)
V2_PATTERNS = (
    r"^\s*#\s*hc\s*:",
    r"^\s*%%source\b",
    r"@handcalc\([^)]*\b(?:render_context|display|docstring)\s*=",
)
_V1 = [re.compile(p, re.M) for p in V1_PATTERNS]
_V2 = [re.compile(p, re.M) for p in V2_PATTERNS]
_RENDER_LINE = re.compile(r"^\s*%%render(?:[ \t]+([^\n]*))?$", re.M)
_PLAIN_IMPORT = re.compile(r"^\s*import\s+handcalcs\s*(?:#.*)?$", re.M)


def has_v1_render_args(text: str) -> bool:
    """A ``%%render`` line with v1's arguments (``params``, ``long``, a precision ...)."""
    for match in _RENDER_LINE.finditer(text):
        for word in (match.group(1) or "").split():
            if "=" in word:  # a v2 argument (inputs=, destination=)
                break
            if word.isdigit() or word == "sci_not":
                return True
            if any(o.startswith(word) or word.startswith(o) for o in V1_OVERRIDES):
                return True
    return False


def source_version(texts: list[str]) -> str | None:
    """
    ``"v1"`` or ``"v2"`` for the source of a notebook's code cells (or one
    script), or None when nothing tells them apart. v1 signs win: a notebook
    half converted by hand still needs converting.
    """
    text = "\n".join(texts)
    if any(p.search(text) for p in _V1) or has_v1_render_args(text):
        return "v1"
    if any(p.search(text) for p in _V2):
        return "v2"
    if _RENDER_LINE.search(text) and _PLAIN_IMPORT.search(text):
        return "v2"
    return None

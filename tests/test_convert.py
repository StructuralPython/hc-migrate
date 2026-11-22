"""Converting v1 cells and Python source (hc_migrate.convert)."""

import pytest

from hc_migrate.convert import (
    Names,
    Options,
    convert_python,
    convert_render_cell,
    migrate_calc_lines,
    parse_render_args,
    scan_names,
    split_comment,
)


def render(source: str, **options) -> str:
    return convert_render_cell(source, Options(**options)).source


def python(source: str, **options) -> str:
    names = Names()
    scan_names(source, names)
    return convert_python(source, names, Options(**options)).source


def warnings(result) -> list[str]:
    return [n.message for n in result.notes if n.level == "warning"]


# --- %%render arguments ---


@pytest.mark.parametrize(
    "line, override, precision, sci",
    [
        ("", "", None, False),
        ("params", "params", None, False),
        ("long 2", "long", 2, False),
        ("2 long", "long", 2, False),
        ("symbolic", "symbolic", None, False),
        ("short", "short", None, False),
        ("3 sci_not", "", 3, True),
        ("param", "params", None, False),  # v1 matched part of a word
        ("LONG", "long", None, False),
    ],
)
def test_parse_render_args(line, override, precision, sci):
    args = parse_render_args(line)
    assert (args.override, args.precision, args.sci_not) == (override, precision, sci)


def test_loose_argument_is_reported():
    result = convert_render_cell("%%render param\na = 1", Options())
    assert "v1 read the argument 'param' as 'params'" in warnings(result)


# --- %%render cells ---


@pytest.mark.parametrize(
    "first, header",
    [
        ("%%render", "%%render\n"),
        ("%%render long", "%%render\n# hc: -m\n"),
        ("%%render 2", "%%render\n# hc: -f .2f\n"),
        ("%%render long 2", "%%render\n# hc: -m -f .2f\n"),
        ("%%render 2 sci_not", "%%render\n# hc: -f .2e\n"),
        ("%%render sci_not", "%%render\n# hc: -f .3e\n"),
        ("%%render symbolic", '%%render\n# hc: mode = "ass sym"\n'),
        ("%%render short", "%%render\n"),
        ("%%tex", "%%source latex\n"),
        ("%%tex long 2", "%%source latex\n# hc: -m -f .2f\n"),
        ("%%render sympy", "%%render\n# hc: -y\n"),
        ("%%render sympy 2", "%%render\n# hc: -f .2f\n# hc: -y\n"),
    ],
)
def test_render_arguments_become_commands(first, header):
    assert render(f"{first}\nc = a + b") == f"{header}c = a + b"


def test_keep_v1_precision():
    assert render("%%render\nc = a + b", keep_v1_precision=True) == (
        "%%render\n# hc: -f .3f\nc = a + b"
    )


def test_params_cell_gets_a_grid_per_run():
    source = "%%render params\na = 1\nb = 2\n\nc = 3\nd = a + c\n"
    assert render(source) == (
        "%%render\n# hc: -g\na = 1\nb = 2\n\n# hc: -g\nc = 3\nd = a + c\n"
    )


def test_tex_and_sympy_convert_without_warnings():
    for first in ("%%tex", "%%render sympy"):
        result = convert_render_cell(f"{first}\na = 1", Options())
        assert warnings(result) == []
    notes = [
        n.message for n in convert_render_cell("%%render sympy\na = 1", Options()).notes
    ]
    assert any("-y" in note and "SymPy" in note for note in notes)


# --- Calculation lines ---


def calc(source: str) -> str:
    lines = source.splitlines(keepends=True)
    return "".join(migrate_calc_lines(lines, 1, False, []))


def test_intertext_becomes_a_comment_paragraph():
    assert calc("## Loads\na = 1") == "# Loads\na = 1"


def test_hidden_comments_are_wrapped():
    assert calc("# note one\n# note two\na = 1") == (
        "# hc: -i\n# note one\n# note two\n# hc: -s\na = 1"
    )


def test_a_hidden_comment_last_in_the_cell():
    assert calc("a = 1\n# the end") == "a = 1\n# hc: -i\n# the end\n# hc: -s"


def test_ignore_becomes_hc_i():
    assert calc("a = 1 # ignore\nb = 2") == "a = 1  # hc: -i\nb = 2"
    assert calc("a = 1 #ignore") == "a = 1  # hc: -i"


def test_indented_lines_keep_their_indent():
    assert calc("if a:\n    ## why\n    b = 1") == "if a:\n    # why\n    b = 1"


def test_inline_comments_and_strings_are_left_alone():
    source = 'a = 1  # kN\ns = "# not a comment"\nt = """\n# inside a string\n"""\n'
    assert calc(source) == source


def test_v2_commands_are_left_alone():
    assert calc("# hc: -m\na = 1") == "# hc: -m\na = 1"


@pytest.mark.parametrize(
    "line, code, comment",
    [
        ("a = 1  # kN", "a = 1  ", " kN"),
        ('s = "#x"  # c', 's = "#x"  ', " c"),
        ("a = 1", "a = 1", None),
    ],
)
def test_split_comment(line, code, comment):
    assert split_comment(line) == (code, comment)


# --- Imports ---


@pytest.mark.parametrize(
    "before, after",
    [
        ("import handcalcs.render", "import handcalcs"),
        ("import handcalcs.render as hc", "import handcalcs as hc"),
        ("from handcalcs import render", "import handcalcs"),
        ("from handcalcs.decorator import handcalc", "from handcalcs import handcalc"),
        (
            "from handcalcs.global_config import set_option",
            "from handcalcs import set_option",
        ),
        ("%load_ext handcalcs.render", "import handcalcs"),
        ("import handcalcs", "import handcalcs"),
    ],
)
def test_imports(before, after):
    assert python(before + "\n") == after + "\n"


def test_internal_modules_are_flagged():
    result = convert_python(
        "from handcalcs.handcalcs import LatexRenderer\n", Names(), Options()
    )
    assert "v1 internals" in warnings(result)[0]


# --- Decorators ---

FUNCTION = "def f(a):\n    b = a * 2\n    return b\n"


@pytest.mark.parametrize(
    "decorator, converted",
    [
        ("@handcalc()", "@handcalc(LatexRenderer())"),
        ("@handcalc", "@handcalc(LatexRenderer())"),
        (
            '@handcalc(override="long")',
            '@handcalc(LatexRenderer(), render_context={"multiline": True})',
        ),
        (
            '@handcalc("long", 2)',
            '@handcalc(LatexRenderer(), render_context={"format_code": ".2f", "multiline": True})',
        ),
        (
            "@handcalc(precision=1, scientific_notation=True)",
            '@handcalc(LatexRenderer(), render_context={"format_code": ".1e"})',
        ),
        (
            '@handcalc(override="params")',
            '@handcalc(LatexRenderer(), render_context={"param_line": True})',
        ),
        (
            '@handcalc(override="symbolic")',
            '@handcalc(LatexRenderer(), render_context={"mode": "ass sym"})',
        ),
        ("@handcalc(jupyter_display=True)", "@handcalc(LatexRenderer(), display=True)"),
        ("@handcalcs.handcalc()", "@handcalcs.handcalc(LatexRenderer())"),
    ],
)
def test_decorators(decorator, converted):
    result = convert_python(f"{decorator}\n{FUNCTION}", Names(), Options())
    assert result.source == f"{converted}\n{FUNCTION}"
    assert result.needs_latex_renderer


def test_aliased_decorator():
    source = f"from handcalcs.decorator import handcalc as hc\n@hc()\n{FUNCTION}"
    assert (
        python(source)
        == f"from handcalcs import handcalc as hc\n@hc(LatexRenderer())\n{FUNCTION}"
    )


def test_docstring_is_left_out_as_in_v1():
    source = '@handcalc()\ndef f(a):\n    """Doc."""\n    b = a\n    return b\n'
    assert "@handcalc(LatexRenderer(), docstring=False)" in python(source)


def test_decorated_body_gets_v1_comment_conventions():
    source = (
        "@handcalc()\ndef f(a):\n    # note\n    ## Step\n    b = a\n    return b\n"
    )
    assert python(source) == (
        "@handcalc(LatexRenderer())\ndef f(a):\n    # hc: -i\n    # note\n"
        "    # hc: -s\n    # Step\n    b = a\n    return b\n"
    )


def test_v2_decorator_is_left_alone():
    source = f"@handcalc(LatexRenderer(), render_context={{}})\n{FUNCTION}"
    assert python(source) == source


@pytest.mark.parametrize(
    "decorator, expected",
    [
        ('@handcalc(left="\\\\[")', "left="),
        ("@handcalc(record=True)", "record=True"),
        ("@handcalc(precision=p)", "isn't a literal"),
    ],
)
def test_decorator_arguments_without_v2_equivalent_are_flagged(decorator, expected):
    result = convert_python(f"{decorator}\n{FUNCTION}", Names(), Options())
    assert any(expected in w for w in warnings(result))


def test_unpacked_return_is_swapped():
    source = f"@handcalc()\n{FUNCTION}latex, value = f(2)\n"
    assert python(source).endswith("value, latex = f(2)\n")


def test_other_uses_of_the_return_are_flagged():
    source = f"@handcalc()\n{FUNCTION}print(f(2)[0])\n"
    names = Names()
    scan_names(source, names)
    result = convert_python(source, names, Options())
    assert any("returns (value, latex)" in w for w in warnings(result))


def test_display_true_returns_only_the_value():
    source = f"@handcalc(jupyter_display=True)\n{FUNCTION}value = f(2)\n"
    names = Names()
    scan_names(source, names)
    result = convert_python(source, names, Options())
    assert not warnings(result)


# --- set_option and line magics ---


@pytest.mark.parametrize(
    "before, after",
    [
        (
            'handcalcs.set_option("display_precision", 2)',
            'handcalcs.set_option("format_code", ".2f")',
        ),
        (
            'handcalcs.set_option("param_columns", 4)',
            'handcalcs.set_option("param_cols", 4)',
        ),
        (
            'handcalcs.set_option("use_scientific_notation", True)',
            'handcalcs.set_option("format_code", ".3e")',
        ),
    ],
)
def test_set_option(before, after):
    assert python(f"import handcalcs\n{before}\n") == f"import handcalcs\n{after}\n"


def test_imported_set_option():
    source = 'from handcalcs import set_option\nset_option("display_precision", 1)\n'
    assert python(source).endswith('set_option("format_code", ".1f")\n')


def test_removed_option_is_commented_out():
    out = python(
        'import handcalcs\nhandcalcs.set_option("latex_block_start", "\\\\[")\n'
    )
    assert '# handcalcs.set_option("latex_block_start"' in out
    assert "renderer class attribute" in out


def test_decimal_separator_magic_is_commented_out():
    assert python("%decimal_separator ,\n").startswith("# %decimal_separator ,")


def test_cell_that_is_not_python():
    result = convert_python("%%bash\nls -la\nif [ ]; then fi\n", Names(), Options())
    assert result.source == "%%bash\nls -la\nif [ ]; then fi\n"
    assert any("not valid Python" in w for w in warnings(result))

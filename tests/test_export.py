"""
Exporting a notebook as a handcalcs v2 script (hc_migrate.export), including
the cases nb_pyexporter covered: front matter, magics, the CLI.
"""

import ast
import json
import shutil
from pathlib import Path

import nbformat
import pytest
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook, new_raw_cell

from hc_migrate.cli import main
from hc_migrate.detect import source_version
from hc_migrate.export import (
    ExportOptions,
    command_settings,
    export_notebook,
    fstring_template,
    markdown_lines,
)

FIXTURE = Path(__file__).parent / "fixtures" / "v1_beam.ipynb"


def make_nb(*cells):
    return new_notebook(cells=list(cells))


def result(nb, **options):
    options.setdefault("source", "auto")
    return export_notebook(json.loads(nbformat.writes(nb)), ExportOptions(**options))


def export(nb, **options) -> str:
    return result(nb, **options).text


def notes(nb, **options) -> list[str]:
    return [str(note) for _, note in result(nb, **options).notes]


HANDCALCS_NB = make_nb(
    new_raw_cell("---\ntitle: Beam check\nauthor: Me\n---\n"),
    new_code_cell(
        "%matplotlib inline\nimport handcalcs.render\nimport forallpeople as si"
    ),
    new_markdown_cell("## Loads"),
    new_code_cell("%%render params 2\nw = 5.0  # kN/m\nL = 6.0  # m\n\n\n\n"),
    new_code_cell("%%render long\nM = w * L**2 / 8"),
    new_code_cell("!pip install handcalcs"),
)


# --- The whole notebook ----------------------------------------------------------


def test_v1_notebook_exports_as_v2_script():
    # Front matter and magics go; the setup cell is hidden; v1's 'params 2'
    # and 'long' become comment commands, set back after their cells.
    assert export(HANDCALCS_NB) == (
        "# hc: -i\n"
        "import handcalcs\n"
        "import forallpeople as si\n"
        "\n"
        "# hc: -s\n"
        "\n"
        "### Loads\n"
        "\n"
        "# hc: -f .2f\n"
        "# hc: -g\n"
        "w = 5.0  # kN/m\n"
        "L = 6.0  # m\n"
        '# hc: format_code = ".5g"\n'
        "\n"
        "# hc: -m\n"
        "M = w * L**2 / 8\n"
        "# hc: multiline = False\n"
    )


def test_v2_notebook_is_not_migrated():
    nb = make_nb(
        new_code_cell("import handcalcs"),
        new_code_cell("%%render\n## Section\n# A comment shown in v2\na = 1"),
    )
    assert "## Section\n# A comment shown in v2\na = 1" in export(nb)


def test_from_v1_forces_migration():
    nb = make_nb(new_code_cell("%%render\n## Text between equations\na = 1"))
    assert "## Text" in export(nb)  # nothing tells: v2
    assert "could not tell" in notes(nb)[0]
    assert "# Text between equations" in export(nb, source="v1")


def test_output_parses():
    ast.parse(export(HANDCALCS_NB))


# --- Markdown ----------------------------------------------------------------------


def test_markdown_headings_keep_their_level():
    assert markdown_lines("# Title\n## Section\n### Sub") == [
        "## Title",
        "### Section",
        "#### Sub",
    ]


def test_markdown_paragraphs_and_list_items_are_kept_apart():
    assert markdown_lines("One\nstill one\n\nTwo\n\n* a\n* b") == [
        "# One",
        "# still one",
        "# hc: -b",
        "# Two",
        "# hc: -b",
        "# * a",
        "# hc: -b",
        "# * b",
    ]


def test_no_break_right_after_a_heading():
    assert markdown_lines("# Title\n\nText") == ["## Title", "# Text"]


def test_fenced_code_is_text():
    assert markdown_lines("```\n# not a heading\n```") == [
        "# ```",
        "# # not a heading",
        "# ```",
    ]


def test_br_starts_a_paragraph():
    assert markdown_lines("From:<br>a book") == ["# From:", "# hc: -b", "# a book"]


def test_images_are_left_out_with_a_warning():
    nb = make_nb(new_markdown_cell("Look:\n![fig](attachment:abc.png)"))
    assert "fig" not in export(nb)
    assert any("image" in n for n in notes(nb))


def test_front_matter_in_markdown_cell_keeps_rest():
    nb = make_nb(
        new_markdown_cell("---\ntitle: X\n---\n# Heading"), new_code_cell("a = 1")
    )
    assert export(nb).startswith("## Heading\n")


def test_horizontal_rule_later_is_not_front_matter():
    nb = make_nb(new_code_cell("a = 1"), new_markdown_cell("---\ntext\n---"))
    assert "# text" in export(nb)


# --- %%render cells ------------------------------------------------------------------


def test_render_cell_settings_are_set_back():
    nb = make_nb(
        new_code_cell("import handcalcs"),
        new_code_cell("%%render\n# hc: -m -p\n# hc: mode = 'ass sym'\na = 1"),
        new_code_cell("%%render\nb = 2"),
    )
    assert '# hc: mode = "full"; multiline = False; param_line = False\n' in export(nb)


def test_format_code_is_set_back_to_set_option_value():
    nb = make_nb(
        new_code_cell('import handcalcs\nhandcalcs.set_option("format_code", ".3f")'),
        new_code_cell("%%render\n# hc: -f .1f\na = 1 / 3"),
    )
    assert '# hc: format_code = ".3f"' in export(nb)


def test_hidden_region_left_open_is_closed():
    nb = make_nb(
        new_code_cell("import handcalcs"),
        new_code_cell("%%render\na = 1\n# hc: -i\nb = 2"),
        new_code_cell("%%render\nc = 3"),
    )
    assert "b = 2\n# hc: -s\n" in export(nb)


def test_inline_commands_need_no_reset():
    nb = make_nb(
        new_code_cell("import handcalcs"),
        new_code_cell("%%render\na = 1  # hc: -f .2f"),
    )
    assert "format_code =" not in export(nb)


@pytest.mark.parametrize(
    "command, settings, visibility",
    [
        ("-m -f .2f", {"multiline": True, "format_code": ".2f"}, None),
        ("--mode ass sym -p", {"mode": "ass sym", "param_line": True}, None),
        ("-i", {}, "hide"),
        ("-s", {}, "show"),
        ("-s A_s > A_req", {}, "hide"),
        ("multiline = False; ignore = True", {"multiline": False}, "hide"),
        ("-g -c 2", {"param_cols": "2"}, None),
    ],
)
def test_command_settings(command, settings, visibility):
    assert command_settings(command) == (settings, visibility)


def test_stacked_cell_magics():
    nb = make_nb(
        new_code_cell("import handcalcs"), new_code_cell("%%time\n%%render\nx = 1")
    )
    assert export(nb).endswith("\n\nx = 1\n")


def test_render_arguments_are_reported():
    nb = make_nb(
        new_code_cell("import handcalcs"),
        new_code_cell("%%render inputs=case\nx = 1"),
    )
    assert any("don't apply to a script" in n for n in notes(nb))


# --- Other code cells ----------------------------------------------------------------


def test_code_cells_are_hidden_and_share_a_block():
    nb = make_nb(new_code_cell("import handcalcs\nimport math"), new_code_cell("a = 1"))
    assert export(nb) == (
        "# hc: -i\nimport handcalcs\nimport math\n\na = 1\n# hc: -s\n"
    )


def test_show_code():
    nb = make_nb(new_code_cell("import handcalcs"), new_code_cell("a = 1"))
    assert export(nb, show_code=True) == "import handcalcs\n\na = 1\n"


def test_render_line_magic_is_shown():
    nb = make_nb(new_code_cell("import handcalcs\na = 2\n%render b = a * 3\nc = b"))
    assert export(nb) == (
        "# hc: -i\nimport handcalcs\n\na = 2\n# hc: -s\nb = a * 3\n"
        "# hc: -i\nc = b\n# hc: -s\n"
    )


def test_non_python_cell_magic_is_commented():
    nb = make_nb(new_code_cell("%%bash\necho hi"), new_code_cell("a = 1"))
    out = export(nb)
    assert "# %%bash" in out and "# echo hi" in out
    ast.parse(out)


def test_invalid_python_is_commented_out_with_a_warning():
    nb = make_nb(new_code_cell("def broken(:\n    pass"))
    assert "# def broken(:" in export(nb)
    assert any("not valid Python" in n for n in notes(nb))


def test_percent_inside_valid_code_untouched():
    src = 's = """\n%d items\n"""\ny = (10\n%3)'
    out = export(make_nb(new_code_cell(src)), black=False)
    assert "%d items" in out and "%3" in out


def test_command_inside_a_hidden_function_is_hidden_again():
    # A -s inside a function body would show what follows it.
    nb = make_nb(
        new_code_cell(
            "def f(x):\n    # hc: -i\n    # note\n    # hc: -s\n    return x\ny = f(1)"
        )
    )
    assert "    return x\n\n\n# hc: -i\ny = f(1)\n# hc: -s" in export(nb)


def test_displayed_markdown_becomes_a_template():
    nb = make_nb(
        new_code_cell("a = 2\ndisplay(Markdown(f'### Use {a} bars at {a/3:.2f} m'))")
    )
    assert (
        '# hc: -s\n#### Use {{ a }} bars at {{ "%.2f"|format(a / 3) }} m\n'
        in export(nb)
    )


def test_fstring_template_refuses_what_jinja_cant_fill():
    tree = ast.parse("f'{x!r}'\nf'{x:>10}'\nf'{x:,.2f}'")
    assert [fstring_template(s.value) for s in tree.body] == [None, None, None]


def test_other_output_gets_a_warning():
    cell = new_code_cell("x = 1\nx")
    cell.outputs = [nbformat.v4.new_output("execute_result", data={"text/plain": "1"})]
    assert any("shows output" in n for n in notes(make_nb(cell)))


def test_displaying_handcalc_function_calls_are_shown():
    nb = make_nb(
        new_code_cell(
            "from handcalcs import handcalc\n"
            "from handcalcs.renderers import LatexRenderer"
        ),
        new_code_cell(
            "@handcalc(LatexRenderer(), display=True)\n"
            "def area(b, h):\n    A = b * h\n    return A"
        ),
        new_code_cell("A_1 = area(2, 3)"),
    )
    out = export(nb)
    assert "@handcalc" not in out
    assert "# hc: -s\nA_1 = area(2, 3)\n" in out
    assert any("@handcalc functions (area)" in n for n in notes(nb))


def test_raw_cell_is_dropped():
    nb = make_nb(new_code_cell("import handcalcs"), new_raw_cell("raw text"))
    assert "raw text" not in export(nb)
    assert any("raw cell dropped" in n for n in notes(nb))


def test_black_failure_falls_back(caplog, monkeypatch):
    import black

    def boom(*args, **kwargs):
        raise ValueError("nope")

    monkeypatch.setattr(black, "format_str", boom)
    assert "a=1" in export(make_nb(new_code_cell("a=1")))
    assert "black could not format" in caplog.text


# --- Detection -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "texts, version",
    [
        (["import handcalcs.render"], "v1"),
        (["%load_ext handcalcs.render"], "v1"),
        (["from handcalcs.decorator import handcalc"], "v1"),
        (["%%render params\na = 1"], "v1"),
        (["%%render 3\na = 1"], "v1"),
        (['handcalcs.set_option("display_precision", 2)'], "v1"),
        (["@handcalc(jupyter_display=True)\ndef f(): pass"], "v1"),
        (["%%tex\na = 1"], "v1"),
        (["import handcalcs", "%%render\na = 1"], "v2"),
        (["%%render\n# hc: -f .2f\na = 1"], "v2"),
        (["%%source latex\na = 1"], "v2"),
        (["%%render inputs=case\na = 1"], None),
        (["%%render\na = 1"], None),
        (["import handcalcs.render", "%%render\n# hc: -m\na = 1"], "v1"),
        # Commented out by a conversion: not v1.
        (["import handcalcs", '# handcalcs.set_option("custom_symbols", {})'], None),
    ],
)
def test_source_version(texts, version):
    assert source_version(texts) == version


# --- The command -----------------------------------------------------------------------


def test_cli_single_file_default_output(tmp_path):
    nb_path = tmp_path / "calc.ipynb"
    nbformat.write(HANDCALCS_NB, nb_path)
    assert main([str(nb_path), "-q"]) == 0
    assert (tmp_path / "calc.py").read_text(encoding="utf-8") == export(HANDCALCS_NB)


def test_cli_single_file_into_a_directory(tmp_path):
    nb_path = tmp_path / "calc.ipynb"
    nbformat.write(HANDCALCS_NB, nb_path)
    (tmp_path / "out").mkdir()
    assert main([str(nb_path), "-o", str(tmp_path / "out"), "-q"]) == 0
    assert (tmp_path / "out" / "calc.py").exists()


def test_cli_directory_in_place_skips_existing(tmp_path):
    src = tmp_path / "src"
    (src / "a").mkdir(parents=True)
    (src / ".ipynb_checkpoints").mkdir()
    for rel in ["top.ipynb", "a/one.ipynb", ".ipynb_checkpoints/top-checkpoint.ipynb"]:
        nbformat.write(HANDCALCS_NB, src / rel)
    (src / "a" / "one.py").write_text("sentinel", encoding="utf-8")
    assert main([str(src), "-q"]) == 0
    assert (src / "top.py").exists()
    assert (src / "a" / "one.py").read_text(encoding="utf-8") == "sentinel"
    assert not (src / ".ipynb_checkpoints" / "top-checkpoint.py").exists()
    assert main([str(src), "-q", "--overwrite"]) == 0
    assert (src / "a" / "one.py").read_text(encoding="utf-8") != "sentinel"


def test_cli_mirrors_tree(tmp_path):
    src = tmp_path / "src"
    (src / "a" / "b").mkdir(parents=True)
    for rel in ["top.ipynb", "a/one.ipynb", "a/b/two.ipynb"]:
        nbformat.write(HANDCALCS_NB, src / rel)
    (src / "a" / "data.csv").write_text("x\n1\n", encoding="utf-8")
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "-q"]) == 0
    produced = sorted(
        p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()
    )
    assert produced == ["a/b/two.py", "a/data.csv", "a/one.py", "top.py"]
    out2 = tmp_path / "out2"
    assert main([str(src), "-o", str(out2), "-q", "--only-converted"]) == 0
    assert not (out2 / "a" / "data.csv").exists()


def test_cli_notebook_and_script_with_one_name(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    nbformat.write(HANDCALCS_NB, src / "calc.ipynb")
    (src / "calc.py").write_text("import handcalcs.render\n", encoding="utf-8")
    assert main([str(src), "-o", str(tmp_path / "out")]) == 0
    assert "another file was written" in capsys.readouterr().out


def test_cli_expands_tilde(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    nbformat.write(HANDCALCS_NB, tmp_path / "calc.ipynb")
    assert main(["~/calc.ipynb", "-o", "~/out", "-q"]) == 0
    assert (tmp_path / "out" / "calc.py").exists()
    assert not (tmp_path / "~").exists()


def test_cli_reports_bad_notebook(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    (src / "bad.ipynb").write_text("not json", encoding="utf-8")
    nbformat.write(HANDCALCS_NB, src / "good.ipynb")
    assert main([str(src), "-o", str(tmp_path / "out"), "-q"]) == 1
    assert (tmp_path / "out" / "good.py").exists()
    assert not (tmp_path / "out" / "bad.py").exists()
    assert "FAILED" in capsys.readouterr().err


def test_cli_dry_run_writes_nothing(tmp_path):
    shutil.copy(FIXTURE, tmp_path / "beam.ipynb")
    assert main([str(tmp_path / "beam.ipynb"), "--dry-run", "-q"]) == 0
    assert not (tmp_path / "beam.py").exists()


# --- The script renders ------------------------------------------------------------------


def test_exported_fixture_renders_with_handcalcs(tmp_path, monkeypatch):
    pytest.importorskip("handcalcs")
    pytest.importorskip("sympy")
    from handcalcs import HandCalcs
    from handcalcs.parsing import line_values
    from handcalcs.renderers import ASCIIRenderer

    if not hasattr(line_values, "source_filename"):
        pytest.skip("@handcalc functions in a script need handcalcs#394")

    script = tmp_path / "beam.py"
    text = FIXTURE.read_text(encoding="utf-8")
    script.write_text(
        export_notebook(text, ExportOptions(source="auto")).text, encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    out = HandCalcs(ASCIIRenderer())(script)
    assert "Beam design" in out  # the Markdown heading
    assert "import" not in out and "set_option" not in out  # hidden code
    assert "Section inputs" not in out  # a comment v1 didn't show
    assert "Moment of inertia" in out  # v1's '##' text between equations
    assert "chk" not in out  # '# ignore'
    assert "V_max = shear(5, 6)" in out  # a displaying @handcalc call


def test_nbconvert_exporter_writes_what_the_command_writes():
    pytest.importorskip("nbconvert")
    from hc_migrate.nbconvert_exporter import HandcalcsScriptExporter

    body, resources = HandcalcsScriptExporter().from_notebook_node(HANDCALCS_NB)
    assert body == export(HANDCALCS_NB)
    assert resources["output_extension"] == ".py"

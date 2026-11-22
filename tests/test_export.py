import ast

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook, new_raw_cell

from nb_pyexporter import CleanPythonExporter, main
from nb_pyexporter.transforms import unwrap_get_ipython


def make_nb(*cells):
    nb = new_notebook(cells=list(cells))
    for i, cell in enumerate(nb.cells, start=1):
        if cell.cell_type == "code":
            cell.execution_count = i + 10
    return nb


def export(nb, **kw):
    body, _ = CleanPythonExporter(**kw).from_notebook_node(nb)
    return body


HANDCALCS_NB = make_nb(
    new_raw_cell("---\ntitle: Beam check\nauthor: Me\n---\n"),
    new_code_cell("%matplotlib inline\nimport handcalcs.render\nimport forallpeople as si"),
    new_markdown_cell("## Loads"),
    new_code_cell("%%render params 2\nw = 5.0  # kN/m\nL = 6.0  # m\n\n\n\n"),
    new_code_cell("%%render long\nM = w * L**2 / 8"),
    new_code_cell("!pip install handcalcs"),
)


def test_full_handcalcs_notebook():
    out = export(HANDCALCS_NB)
    assert out == (
        "import handcalcs\n"
        "import forallpeople as si\n"
        "\n"
        "# ## Loads\n"
        "\n"
        "w = 5.0  # kN/m\n"
        "L = 6.0  # m\n"
        "\n"
        "M = w * L**2 / 8\n"
    )
    ast.parse(out)


def test_no_shebang_prompts_or_magics():
    out = export(HANDCALCS_NB)
    assert not out.startswith("#!")
    assert "coding" not in out
    assert "# In[" not in out
    assert "%%" not in out and "get_ipython" not in out
    assert "title:" not in out


def test_front_matter_in_markdown_cell_keeps_rest():
    nb = make_nb(new_markdown_cell("---\ntitle: X\n---\n# Heading"), new_code_cell("a = 1"))
    assert export(nb) == "# # Heading\n\na = 1\n"


def test_horizontal_rule_later_is_not_front_matter():
    nb = make_nb(new_code_cell("a = 1"), new_markdown_cell("---\ntext\n---"))
    assert "# text" in export(nb)


def test_non_python_cell_magic_is_commented():
    nb = make_nb(new_code_cell("%%bash\necho hi"), new_code_cell("a = 1"))
    out = export(nb)
    assert "# %%bash" in out and "# echo hi" in out
    ast.parse(out)


def test_stacked_cell_magics():
    nb = make_nb(new_code_cell("%%time\n%%render\nx = 1"))
    assert export(nb) == "x = 1\n"


def test_percent_inside_valid_code_untouched():
    src = 's = """\n%d items\n"""\ny = (10\n%3)'
    nb = make_nb(new_code_cell(src))
    out = export(nb, use_black=False)
    assert "%d items" in out and "%3" in out


def test_unwrap_get_ipython_calls():
    code = (
        "get_ipython().run_line_magic('matplotlib', 'inline')\n"
        "get_ipython().run_cell_magic('render', 'params', 'a = 1\\nb = a + 2\\n')\n"
        "files = get_ipython().getoutput('ls')\n"
        "if True:\n"
        "    get_ipython().system('echo hi')\n"
    )
    assert unwrap_get_ipython(code) == "a = 1\nb = a + 2\nif True:\n    pass\n"


def test_handcalcs_import_updated_and_deduped():
    nb = make_nb(
        new_code_cell("import handcalcs.render\nimport math"),
        new_code_cell("from handcalcs import render  # v1\nimport handcalcs"),
    )
    assert export(nb) == "import handcalcs\nimport math\n"


def test_black_failure_falls_back(caplog):
    nb = make_nb(new_code_cell("def broken(:\n    pass"))
    out = export(nb)
    assert "def broken(:" in out
    assert "black could not format" in caplog.text


def test_cli_mirrors_tree(tmp_path):
    src = tmp_path / "src"
    (src / "a" / "b").mkdir(parents=True)
    (src / ".ipynb_checkpoints").mkdir()
    for rel in ["top.ipynb", "a/one.ipynb", "a/b/two.ipynb", ".ipynb_checkpoints/top-checkpoint.ipynb"]:
        nbformat.write(HANDCALCS_NB, src / rel)
    out = tmp_path / "out"

    assert main([str(src), str(out), "-q"]) == 0
    produced = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.py"))
    assert produced == ["a/b/two.py", "a/one.py", "top.py"]
    assert (out / "a/b/two.py").read_text(encoding="utf-8") == export(HANDCALCS_NB)

    # existing files are skipped unless --overwrite
    (out / "top.py").write_text("sentinel", encoding="utf-8")
    assert main([str(src), str(out), "-q"]) == 0
    assert (out / "top.py").read_text(encoding="utf-8") == "sentinel"
    assert main([str(src), str(out), "-q", "--overwrite"]) == 0
    assert (out / "top.py").read_text(encoding="utf-8") != "sentinel"


def test_cli_single_file_default_output(tmp_path):
    nb_path = tmp_path / "calc.ipynb"
    nbformat.write(HANDCALCS_NB, nb_path)
    assert main([str(nb_path), "-q"]) == 0
    assert (tmp_path / "calc.py").exists()


def test_cli_expands_tilde(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    nbformat.write(HANDCALCS_NB, tmp_path / "calc.ipynb")
    assert main(["~/calc.ipynb", "~/out", "-q"]) == 0
    assert (tmp_path / "out" / "calc.py").exists()
    assert not (tmp_path / "~").exists()


def test_cli_reports_bad_notebook(tmp_path):
    (tmp_path / "bad.ipynb").write_text("not json", encoding="utf-8")
    nbformat.write(HANDCALCS_NB, tmp_path / "good.ipynb")
    assert main([str(tmp_path), str(tmp_path / "out"), "-q"]) == 1
    assert (tmp_path / "out" / "good.py").exists()

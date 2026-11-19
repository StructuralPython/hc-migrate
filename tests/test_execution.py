"""
A converted notebook runs with handcalcs v2: every cell succeeds and the
``%%render`` cells display their calculations.
"""

import importlib
import json
import sys
from pathlib import Path

import pytest

from handcalcs_migrate.notebook import Options, convert_notebook

pytest.importorskip("handcalcs")
pytest.importorskip("IPython")

FIXTURE = Path(__file__).parent / "fixtures" / "v1_beam.ipynb"


@pytest.fixture
def shell():
    from IPython.core.interactiveshell import InteractiveShell

    shell = InteractiveShell.instance()
    # handcalcs registers %%render when it is imported in a running shell;
    # importorskip above imported it before this shell existed.
    sys.modules.pop("handcalcs.interfaces.jupyter", None)
    importlib.import_module("handcalcs.interfaces.jupyter")
    yield shell
    sys.modules.pop("handcalcs.interfaces.jupyter", None)
    InteractiveShell.clear_instance()


@pytest.mark.parametrize(
    "options", [Options(), Options(keep_v1_precision=True, v1_names=True)]
)
def test_converted_fixture_runs(shell, options):
    from IPython.utils.capture import capture_output

    converted = json.loads(
        convert_notebook(FIXTURE.read_text(encoding="utf-8"), options).text
    )
    displayed, printed = [], []
    for number, cell in enumerate(converted["cells"], 1):
        if cell["cell_type"] != "code":
            continue
        source = "".join(cell["source"])
        with capture_output() as captured:
            result = shell.run_cell(source)
        assert result.success, f"cell {number} failed:\n{source}\n{captured.stdout}"
        displayed.extend(o.data.get("text/markdown", "") for o in captured.outputs)
        printed.append(captured.stdout)
    # The v1 '%%tex' cell, now '%%source latex', prints its LaTeX.
    assert any("c &= a + 1" in text for text in printed)
    markdown = "\n".join(displayed)
    assert "Moment of inertia" in markdown  # v1 '## ' text, now a paragraph
    assert "Section inputs" not in markdown  # a v1 comment that wasn't shown
    assert "chk" not in markdown  # a '# ignore' line
    assert "300.00" in markdown  # '%%render params 2'


def test_converted_sympy_cell_substitutes(shell):
    # A v1 '%%render sympy' cell, now '# hc: -y', writes the expression in.
    pytest.importorskip("sympy")
    from IPython.utils.capture import capture_output

    from handcalcs_migrate.convert import convert_render_cell

    shell.run_cell("import sympy as sp\nw, L = sp.symbols('w L')\nM_mid = w * L**2 / 8")
    converted = convert_render_cell(
        "%%render sympy\nw = 4\nL = 6\nM = M_mid\n", Options()
    )
    with capture_output() as captured:
        assert shell.run_cell(converted.source).success
    markdown = "\n".join(o.data.get("text/markdown", "") for o in captured.outputs)
    assert "18" in markdown and "\\frac{w" in markdown.replace(" ", "")

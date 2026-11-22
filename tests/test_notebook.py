"""Converting whole notebooks and scripts (hc_migrate.notebook)."""

import json
from pathlib import Path

import pytest

from hc_migrate.notebook import Options, convert_notebook, convert_script

FIXTURE = Path(__file__).parent / "fixtures" / "v1_beam.ipynb"


def notebook(*cells: str, kind: str = "code") -> str:
    return (
        json.dumps(
            {
                "cells": [
                    {
                        "cell_type": kind,
                        "metadata": {},
                        "source": c.splitlines(True),
                        "execution_count": 3,
                        "outputs": [
                            {"output_type": "stream", "name": "stdout", "text": ["x\n"]}
                        ],
                    }
                    for c in cells
                ],
                "metadata": {"kernelspec": {"name": "python3"}},
                "nbformat": 4,
                "nbformat_minor": 5,
            },
            indent=1,
        )
        + "\n"
    )


def sources(text: str) -> list[str]:
    return ["".join(c["source"]) for c in json.loads(text)["cells"]]


def test_fixture_converts():
    result = convert_notebook(FIXTURE.read_text(encoding="utf-8"), Options())
    cells = sources(result.text)
    assert (
        cells[1]
        == "import handcalcs\nfrom handcalcs.renderers import LatexRenderer\nfrom math import sqrt"
    )
    assert cells[3].startswith("%%render\n# hc: -m\n# Moment of inertia\n")
    assert "M_max, latex = moment(5, 6)" in cells[8]
    assert result.changed and len(result.warnings) == 1


def test_metadata_and_outputs_are_kept():
    raw = notebook("import handcalcs.render", "x = 1")
    result = json.loads(convert_notebook(raw, Options()).text)
    original = json.loads(raw)
    assert result["metadata"] == original["metadata"]
    assert result["cells"][1] == original["cells"][1]
    assert result["cells"][0]["outputs"] == original["cells"][0]["outputs"]


def test_clear_outputs_of_converted_cells():
    raw = notebook("import handcalcs.render", "x = 1")
    cells = json.loads(convert_notebook(raw, Options(clear_outputs=True)).text)["cells"]
    assert cells[0]["outputs"] == [] and cells[0]["execution_count"] is None
    assert cells[1]["outputs"]  # not converted, so kept


def test_a_notebook_without_handcalcs_is_unchanged():
    raw = notebook("import numpy as np", "%%timeit\nnp.ones(3)")
    result = convert_notebook(raw, Options())
    assert result.text == raw and not result.uses_handcalcs


def test_a_v2_notebook_is_unchanged():
    raw = notebook("import handcalcs", "%%render\n# hc: -m\na = 1")
    result = convert_notebook(raw, Options())
    assert result.text == raw and not result.changed


def test_other_cell_magics_are_left_alone():
    raw = notebook("import handcalcs.render", "%%bash\nif [ x ]; then ls; fi")
    result = convert_notebook(raw, Options())
    assert sources(result.text)[1] == "%%bash\nif [ x ]; then ls; fi"
    assert not result.warnings


def test_decorator_used_in_another_cell():
    raw = notebook(
        "from handcalcs.decorator import handcalc",
        "@handcalc()\ndef f(a):\n    b = a\n    return b",
        "latex, b = f(1)",
    )
    cells = sources(convert_notebook(raw, Options()).text)
    assert (
        cells[0]
        == "from handcalcs import handcalc\nfrom handcalcs.renderers import LatexRenderer"
    )
    assert cells[2] == "b, latex = f(1)"


def test_latex_renderer_import_without_a_handcalcs_import():
    raw = notebook("@handcalc()\ndef f(a):\n    b = a\n    return b")
    cells = sources(convert_notebook(raw, Options()).text)
    assert cells[0].startswith(
        "from handcalcs.renderers import LatexRenderer\n@handcalc("
    )


def test_v1_names_option():
    raw = notebook("import handcalcs.render", "%%render\nx_a_b = 1")
    cells = sources(convert_notebook(raw, Options(v1_names=True)).text)
    assert cells[0] == (
        "import handcalcs\n"
        'handcalcs.set_option("subscripts", "nested")\n'
        'handcalcs.set_option("greek_prefixes", False)'
    )


def test_string_sources_stay_strings():
    raw = json.dumps(
        {
            "cells": [
                {
                    "cell_type": "code",
                    "metadata": {},
                    "source": "import handcalcs.render",
                    "outputs": [],
                    "execution_count": None,
                }
            ],
            "metadata": {},
            "nbformat": 4,
            "nbformat_minor": 5,
        }
    )
    cell = json.loads(convert_notebook(raw, Options()).text)["cells"][0]
    assert cell["source"] == "import handcalcs"


def test_invalid_json_raises():
    with pytest.raises(ValueError):
        convert_notebook("{not json", Options())


def test_script():
    source = (
        "from handcalcs.decorator import handcalc\n\n"
        "@handcalc(precision=2)\ndef f(a):\n    b = a * 2\n    return b\n\n"
        "latex, b = f(3)\n"
    )
    result = convert_script(source, Options())
    assert result.text == (
        "from handcalcs import handcalc\nfrom handcalcs.renderers import LatexRenderer\n\n"
        '@handcalc(LatexRenderer(), render_context={"format_code": ".2f"})\n'
        "def f(a):\n    b = a * 2\n    return b\n\nb, latex = f(3)\n"
    )


def test_script_without_handcalcs():
    result = convert_script("x = 1  # handy\n", Options())
    assert result.text == "x = 1  # handy\n" and not result.uses_handcalcs

"""Writes tests/fixtures/v1_beam.ipynb, a notebook written for handcalcs v1."""

import json
from pathlib import Path

CELLS = [
    ("markdown", "# Beam design\nA v1 notebook."),
    ("code", "import handcalcs.render\nfrom math import sqrt"),
    (
        "code",
        "%%render params 2\n# Section inputs (not shown in v1)\nb = 300 # mm\nh = 600 # mm\n\nf_c = 35 # MPa",
    ),
    (
        "code",
        "%%render long\n## Moment of inertia\nI_x = b * h**3 / 12\nS_x = I_x / (h / 2)\nchk = I_x / S_x # ignore",
    ),
    ("code", "%%render symbolic\nw = 5\nL = 6\nM = w * L**2 / 8"),
    ("code", "%%render 2 sci_not\nE = 200000.0\nEI = E * I_x"),
    ("code", "%%tex\na = 2\nc = a + 1"),
    ("code", "%%render sympy\nx = 1"),
    (
        "code",
        "from handcalcs.decorator import handcalc\n\n"
        '@handcalc(override="long", precision=2)\n'
        "def moment(w, L):\n"
        '    """Moment of a simple span."""\n'
        "    # a note for readers only\n"
        "    ## Bending moment\n"
        "    M = w * L**2 / 8\n"
        "    return M\n\n"
        "latex, M_max = moment(5, 6)\n"
        "print(latex)",
    ),
    (
        "code",
        "@handcalc(jupyter_display=True)\ndef shear(w, L):\n    V = w * L / 2\n    return V\n\nV_max = shear(5, 6)",
    ),
    (
        "code",
        'handcalcs.set_option("display_precision", 2)\n'
        'handcalcs.set_option("custom_symbols", {"V_dot": "\\\\dot{V}"})\n'
        'handcalcs.set_option("param_columns", 4)',
    ),
]


def notebook(cells):
    return {
        "cells": [
            {
                "cell_type": kind,
                "metadata": {},
                "source": text.splitlines(keepends=True),
                **({"execution_count": None, "outputs": []} if kind == "code" else {}),
            }
            for kind, text in cells
        ],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            }
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


if __name__ == "__main__":
    path = Path(__file__).parent / "fixtures" / "v1_beam.ipynb"
    path.write_text(json.dumps(notebook(CELLS), indent=1) + "\n", encoding="utf-8")

"""The hc-migrate command (hc_migrate.cli)."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from hc_migrate.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "v1_beam.ipynb"


@pytest.fixture
def tree(tmp_path) -> Path:
    """A project: notebooks in folders, a script, data, and things to skip."""
    root = tmp_path / "calcs"
    (root / "beams").mkdir(parents=True)
    (root / "columns" / "steel").mkdir(parents=True)
    shutil.copy(FIXTURE, root / "beams" / "beam.ipynb")
    shutil.copy(FIXTURE, root / "columns" / "steel" / "column.ipynb")
    (root / "lib.py").write_text(
        "from handcalcs.decorator import handcalc\n\n"
        "@handcalc()\ndef area(b, h):\n    A = b * h\n    return A\n",
        encoding="utf-8",
    )
    (root / "data.csv").write_text("b,h\n300,600\n", encoding="utf-8")
    (root / "plain.ipynb").write_text(
        json.dumps({"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}),
        encoding="utf-8",
    )
    (root / ".ipynb_checkpoints").mkdir()
    (root / ".ipynb_checkpoints" / "beam-checkpoint.ipynb").write_text("{}")
    return root


def files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def test_no_arguments_prints_help(capsys):
    assert main([]) == 0
    assert capsys.readouterr().out.startswith("usage: hc-migrate")


def test_one_file_default_output(tmp_path, capsys):
    source = tmp_path / "beam.ipynb"
    shutil.copy(FIXTURE, source)
    assert main([str(source)]) == 0
    converted = tmp_path / "beam_v2.ipynb"
    assert converted.is_file()
    assert source.read_bytes() == FIXTURE.read_bytes()  # the source is unchanged
    out = capsys.readouterr().out
    assert "converted" in out and "1 warning" in out


def test_one_file_with_output(tmp_path):
    dest = tmp_path / "out" / "new.ipynb"
    assert main([str(FIXTURE), "-o", str(dest)]) == 0
    cells = json.loads(dest.read_text(encoding="utf-8"))["cells"]
    assert "".join(cells[3]["source"]).startswith("%%render\n# hc: -m\n")


def test_existing_output_needs_force(tmp_path, capsys):
    dest = tmp_path / "new.ipynb"
    dest.write_text("keep")
    with pytest.raises(SystemExit):
        main([str(FIXTURE), "-o", str(dest)])
    assert "--force" in capsys.readouterr().err
    assert dest.read_text() == "keep"
    assert main([str(FIXTURE), "-o", str(dest), "--force"]) == 0
    assert dest.read_text() != "keep"


def test_directory_tree(tree, capsys):
    assert main([str(tree)]) == 0
    dest = tree.with_name("calcs_v2")
    assert files(dest) == {
        "beams/beam.ipynb",
        "columns/steel/column.ipynb",
        "lib.py",
        "data.csv",
        "plain.ipynb",
    }
    assert "LatexRenderer()" in (dest / "lib.py").read_text(encoding="utf-8")
    assert (dest / "data.csv").read_bytes() == (tree / "data.csv").read_bytes()
    out = capsys.readouterr().out
    assert "3 files converted" in out and "2 copied" in out


def test_only_converted(tree):
    dest = tree.parent / "out"
    main([str(tree), "-o", str(dest), "--only-converted"])
    assert "data.csv" not in files(dest)


def test_exclude(tree):
    dest = tree.parent / "out"
    main([str(tree), "-o", str(dest), "--exclude", "columns", "--exclude", "*.csv"])
    assert files(dest) == {"beams/beam.ipynb", "lib.py", "plain.ipynb"}


def test_dry_run_writes_nothing(tree, capsys):
    assert main([str(tree), "--dry-run"]) == 0
    assert not tree.with_name("calcs_v2").exists()
    assert "Would write" in capsys.readouterr().out


def test_output_inside_source_is_refused(tree, capsys):
    with pytest.raises(SystemExit):
        main([str(tree), "-o", str(tree / "v2")])
    assert "inside SOURCE" in capsys.readouterr().err


def test_output_same_as_source_is_refused(tmp_path, capsys):
    source = tmp_path / "beam.ipynb"
    shutil.copy(FIXTURE, source)
    with pytest.raises(SystemExit):
        main([str(source), "-o", str(source), "--force"])
    assert "never changed" in capsys.readouterr().err


def test_report(tree):
    report = tree.parent / "report.md"
    main([str(tree), "--report", str(report)])
    text = report.read_text(encoding="utf-8")
    assert text.startswith("# handcalcs v1 to v2")
    assert "## beams/beam.ipynb" in text and "**Check by hand:**" in text


def test_quiet_shows_only_files_with_warnings(tree, capsys):
    main([str(tree), "-q"])
    out = capsys.readouterr().out
    assert "lib.py" not in out and "beam.ipynb" in out


def test_invalid_notebook_is_copied_and_reported(tmp_path, capsys):
    root = tmp_path / "src"
    root.mkdir()
    (root / "broken.ipynb").write_text("{not json", encoding="utf-8")
    assert main([str(root)]) == 1
    assert (tmp_path / "src_v2" / "broken.ipynb").read_text() == "{not json"
    assert "FAILED" in capsys.readouterr().err


def test_not_a_notebook(tmp_path, capsys):
    path = tmp_path / "notes.txt"
    path.write_text("x")
    with pytest.raises(SystemExit):
        main([str(path)])
    assert "not a notebook" in capsys.readouterr().err


def test_python_dash_m(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hc_migrate",
            str(FIXTURE),
            "-o",
            str(tmp_path / "x.ipynb"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "x.ipynb").is_file()

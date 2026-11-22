"""Command line interface: convert a notebook or a directory tree of notebooks."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Iterator
from pathlib import Path

import nbformat

from .exporter import CleanPythonExporter

SKIP_DIRS = {".ipynb_checkpoints", "__pycache__", ".venv", "venv", "node_modules"}


def iter_notebooks(root: Path) -> Iterator[Path]:
    """Yield notebooks under ``root``, skipping hidden and checkpoint dirs."""
    for path in sorted(root.rglob("*.ipynb")):
        rel_parts = path.relative_to(root).parts[:-1]
        if any(part in SKIP_DIRS or part.startswith(".") for part in rel_parts):
            continue
        yield path


def plan(source: Path, output: Path | None) -> list[tuple[Path, Path]]:
    """Map each input notebook to its destination ``.py`` path."""
    if source.is_file():
        if output is None:
            dest = source.with_suffix(".py")
        elif output.suffix == ".py":
            dest = output
        else:
            dest = output / source.with_suffix(".py").name
        return [(source, dest)]

    out_root = output if output is not None else source
    return [
        (nb, out_root / nb.relative_to(source).with_suffix(".py"))
        for nb in iter_notebooks(source)
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nb-pyexporter",
        description=(
            "Convert Jupyter notebooks (e.g. handcalcs calculation notebooks) into "
            "clean Python scripts. A directory is searched recursively and its "
            "structure mirrored in the output directory."
        ),
    )
    parser.add_argument("source", type=Path, help="A .ipynb file or a directory of notebooks.")
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        help=(
            "Output directory (mirrors the source tree) or, for a single notebook, "
            "a .py path. Defaults to writing each .py next to its notebook."
        ),
    )
    parser.add_argument(
        "-f", "--overwrite", action="store_true", help="Overwrite existing .py files."
    )
    parser.add_argument("--no-black", action="store_true", help="Skip black formatting.")
    parser.add_argument(
        "-n", "--dry-run", action="store_true", help="Show what would be written, write nothing."
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="Only report errors.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.WARNING)

    # Windows PowerShell passes `~` through literally, so expand it ourselves.
    source: Path = args.source.expanduser()
    if args.output is not None:
        args.output = args.output.expanduser()
    if not source.exists():
        print(f"error: {source} does not exist", file=sys.stderr)
        return 2
    if source.is_file() and source.suffix != ".ipynb":
        print(f"error: {source} is not a .ipynb file", file=sys.stderr)
        return 2

    jobs = plan(source, args.output)
    if not jobs:
        print(f"No notebooks found under {source}", file=sys.stderr)
        return 1

    exporter = CleanPythonExporter(use_black=not args.no_black)
    say = (lambda *_: None) if args.quiet else print
    written = skipped = 0
    failed: list[Path] = []

    for nb_path, dest in jobs:
        if dest.exists() and not args.overwrite:
            say(f"skip   {dest} (exists; use --overwrite)")
            skipped += 1
            continue
        if args.dry_run:
            say(f"would  {nb_path} -> {dest}")
            written += 1
            continue
        try:
            nb = nbformat.read(nb_path, as_version=4)
            body, _ = exporter.from_notebook_node(
                nb, resources={"metadata": {"name": nb_path.stem, "path": str(nb_path.parent)}}
            )
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(body, encoding="utf-8", newline="\n")
        except Exception as exc:
            print(f"FAIL   {nb_path}: {exc}", file=sys.stderr)
            failed.append(nb_path)
            continue
        say(f"wrote  {dest}")
        written += 1

    verb = "would write" if args.dry_run else "written"
    say(f"\n{written} {verb}, {skipped} skipped, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

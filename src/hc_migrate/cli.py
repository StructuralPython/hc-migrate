"""
The ``hc-migrate`` command.

    hc-migrate calc.ipynb --to ipynb -o calc_v2.ipynb  # v1 notebook -> v2 notebook
    hc-migrate calc.ipynb --to py -o calc.py           # notebook -> v2 script
    hc-migrate calcs/ --to py --output scripts         # notebooks -> scripts

Existing files are never changed: a script is written next to its notebook
(or under DEST), and a converted notebook or ``.py`` file is a new file.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .convert import GUIDE
from .export import ExportOptions, export_notebook
from .notebook import FileResult, convert_notebook, convert_script

CONVERTIBLE = (".ipynb", ".py")
DEFAULT_EXCLUDES = (".git", ".ipynb_checkpoints", "__pycache__", ".venv", ".DS_Store")

DESCRIPTION = """\
Two conversions:

  --to ipynb  update notebooks (and .py files) written for handcalcs v1 so
              they work with handcalcs v2. They stay notebooks.
  --to py     turn notebooks, written for handcalcs v1 or v2, into handcalcs
              v2 scripts (.py) that render as the notebook showed (the
              default).

In a script, Markdown cells become comments (prose and headings), %%render
cells become plain lines, and the other code cells run but are hidden. A v1
notebook is converted to v2 on the way.

SOURCE is a file or a directory. A directory is searched for notebooks (and
.py files), and with -o its tree is copied to DEST, the notebooks and Python
files converted. Existing files are never changed.
"""

EPILOG = f"""\
examples:
  hc-migrate beam.ipynb                        writes beam.py
  hc-migrate beam.ipynb -o out/beam.py
  hc-migrate calcs/                            writes a .py next to each notebook
  hc-migrate calcs/ -o scripts --report report.md
  hc-migrate beam.ipynb --to ipynb             writes beam_v2.ipynb (v1 -> v2)
  hc-migrate calcs/ --to ipynb --output v2     writes v2/, the notebooks converted
  hc-migrate calcs/ --dry-run                  only reports what would be written

What changes, and what to check by hand afterwards, is reported for each file.
The handcalcs v1 to v2 guide: {GUIDE}
"""


@dataclass
class Summary:
    exported: int = 0
    converted: int = 0
    unchanged: int = 0
    copied: int = 0
    skipped: int = 0
    failed: int = 0
    warnings: int = 0
    written: set[Path] = field(default_factory=set)
    report: list[str] = field(default_factory=list)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hc-migrate",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    parser.add_argument(
        "source", metavar="SOURCE", type=Path, help="a file or directory"
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="DEST",
        type=Path,
        help="where to write: a file, or a directory for a tree "
        "(default: next to SOURCE)",
    )
    parser.add_argument(
        "--to",
        choices=("py", "ipynb"),
        default="py",
        help="py: notebooks (v1 or v2) become handcalcs v2 scripts (the "
        "default); ipynb: notebooks written for v1 are converted to v2 and stay "
        "notebooks",
    )
    parser.add_argument(
        "--from",
        dest="source_version",
        choices=("auto", "v1", "v2"),
        default="auto",
        help="the handcalcs the source was written for (default: tell from "
        "the source; v2 when nothing tells)",
    )
    parser.add_argument(
        "-f",
        "--force",
        "--overwrite",
        action="store_true",
        help="overwrite files (or DEST) that exist",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="report what would be written, and write nothing",
    )
    parser.add_argument(
        "--report",
        metavar="FILE",
        type=Path,
        help="also write the report to FILE (Markdown)",
    )
    parser.add_argument(
        "--show-code",
        action="store_true",
        help="scripts: show the code cells the notebook didn't render",
    )
    parser.add_argument(
        "--no-black", action="store_true", help="scripts: don't format with black"
    )
    parser.add_argument(
        "--keep-v1-precision",
        action="store_true",
        help="v1: show numbers with 3 decimal places where v1 used its default "
        "(v2's default is 5 significant figures)",
    )
    parser.add_argument(
        "--v1-names",
        action="store_true",
        help="v1: keep v1's nested subscripts (x_a_b) and Greek names (phiM) "
        "with set_option calls",
    )
    parser.add_argument(
        "--clear-outputs",
        action="store_true",
        help="--to ipynb: clear the outputs of converted cells (they show the "
        "v1 render)",
    )
    parser.add_argument(
        "--exclude",
        metavar="PATTERN",
        action="append",
        default=[],
        help="skip files and directories matching PATTERN (repeatable; "
        f"always skipped: {', '.join(DEFAULT_EXCLUDES)})",
    )
    parser.add_argument(
        "--only-converted",
        action="store_true",
        help="with a directory DEST, write only notebooks and Python files, "
        "not the other files",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="report only files with warnings"
    )
    parser.add_argument(
        "-V", "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser


def default_output(source: Path, to: str) -> Path | None:
    """Where to write when no DEST is given; None: next to each notebook."""
    if source.is_dir():
        if to == "py":
            return None
        return source.with_name(source.resolve().name + "_v2")
    if to == "py" and source.suffix == ".ipynb":
        return source.with_suffix(".py")
    return source.with_name(f"{source.stem}_v2{source.suffix}")


def file_dest(source: Path, output: Path | None, to: str) -> Path:
    """Where a single SOURCE file goes: DEST, or a file in DEST if it is a directory."""
    if output is None:
        return default_output(source, to)
    if output.is_dir() or (output.suffix == "" and not output.exists()):
        name = source.with_suffix(".py").name if exports(source, to) else source.name
        return output / name
    return output


def exports(path: Path, to: str) -> bool:
    return to == "py" and path.suffix == ".ipynb"


def convert_file(path: Path, to: str, options: ExportOptions) -> FileResult:
    text = path.read_text(encoding="utf-8")
    if exports(path, to):
        return export_notebook(text, options, path.stem)
    if path.suffix == ".ipynb":
        return convert_notebook(text, options)
    return convert_script(text, options)


def is_excluded(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in (*DEFAULT_EXCLUDES, *patterns))


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def handle_file(
    source: Path,
    dest: Path,
    shown_as: str,
    args: argparse.Namespace,
    options: ExportOptions,
    summary: Summary,
    per_file_force: bool,
) -> None:
    """Convert, export or copy one file and record it in the summary."""
    if source.suffix not in CONVERTIBLE:
        if not args.only_converted:
            if not args.dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
            summary.copied += 1
        return
    if dest.resolve() in summary.written:
        summary.skipped += 1
        print(f"skipped  {shown_as}: another file was written to {dest}")
        return
    if per_file_force and dest.exists() and not args.force:
        summary.skipped += 1
        if not args.quiet:
            print(f"skipped  {shown_as}: {dest} exists (use --force)")
        return
    exporting = exports(source, args.to)
    try:
        result = convert_file(source, args.to, options)
    except (ValueError, UnicodeDecodeError, OSError) as error:
        summary.failed += 1
        if exporting:
            print(f"FAILED   {shown_as}: {error}", file=sys.stderr)
            summary.report.append(f"## {shown_as}\n\nFailed: {error}.\n")
            return
        print(f"FAILED   {shown_as}: {error}; copied unchanged", file=sys.stderr)
        summary.report.append(f"## {shown_as}\n\nFailed: {error}. Copied unchanged.\n")
        if not args.dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
        return
    summary.written.add(dest.resolve())
    if not args.dry_run:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if exporting:
            dest.write_text(result.text, encoding="utf-8", newline="\n")
        elif result.changed:
            dest.write_text(result.text, encoding="utf-8", newline="")
            shutil.copystat(source, dest)
        else:
            shutil.copy2(source, dest)
    if not exporting and not result.uses_handcalcs:
        summary.copied += 1
        return
    warnings = result.warnings
    summary.warnings += len(warnings)
    if exporting:
        summary.exported += 1
        status = "exported"
    elif result.changed:
        summary.converted += 1
        status = "converted"
    else:
        summary.unchanged += 1
        status = "no changes needed"
    changes = [(w, n) for w, n in result.notes if n.level == "change"]
    line = f"{status:<17} {shown_as}"
    if exporting:
        line += f" -> {dest.name}"
    if changes or warnings:
        line += (
            f"  ({plural(len(changes), 'change')}, {plural(len(warnings), 'warning')})"
        )
    if warnings or not args.quiet:
        print(line)
        for where, note in warnings:
            print(f"    warning: {where + ', ' if where else ''}{note}")
    report = [f"## {shown_as}\n", f"{status}.\n"]
    for title, items in (("Check by hand", warnings), ("Changes", changes)):
        if items:
            report.append(f"\n**{title}:**\n")
            report.extend(
                f"- {where + ', ' if where else ''}{note}\n" for where, note in items
            )
    summary.report.append("".join(report))


def walk(source: Path, patterns: list[str]):
    """The files under ``source``, as paths relative to it, in order."""
    for root, dirs, files in os.walk(source):
        dirs[:] = sorted(
            d
            for d in dirs
            if not is_excluded(d, patterns) and not Path(root, d).is_symlink()
        )
        for name in sorted(files):
            if not is_excluded(name, patterns):
                yield Path(root, name).relative_to(source)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        parser.print_help()
        return 0
    args = parser.parse_args(argv)
    # Windows PowerShell passes '~' through as it is.
    source: Path = args.source.expanduser()
    output: Path | None = args.output.expanduser() if args.output else None
    if not source.exists():
        parser.error(f"{source}: no such file or directory")
    if source.is_file() and source.suffix not in CONVERTIBLE:
        parser.error(f"{source}: not a notebook (.ipynb) or Python file (.py)")
    options = ExportOptions(
        source=args.source_version,
        keep_v1_precision=args.keep_v1_precision,
        v1_names=args.v1_names,
        clear_outputs=args.clear_outputs,
        show_code=args.show_code,
        black=not args.no_black,
    )

    summary = Summary()
    if source.is_file():
        dest = file_dest(source, output, args.to)
        if dest.resolve() == source.resolve():
            parser.error("DEST is SOURCE: existing files are never changed")
        if dest.exists() and not (args.force or args.dry_run):
            parser.error(f"{dest} exists: use --force to overwrite it")
        handle_file(source, dest, str(source), args, options, summary, False)
        shown_dest = dest
    elif output is None and args.to == "py":
        # Each notebook's script next to it; nothing else is written.
        for relative in walk(source, args.exclude):
            if relative.suffix == ".ipynb":
                path = source / relative
                handle_file(
                    path,
                    path.with_suffix(".py"),
                    relative.as_posix(),
                    args,
                    options,
                    summary,
                    True,
                )
        shown_dest = source
    else:
        dest = output or default_output(source, args.to)
        if dest.resolve() == source.resolve():
            parser.error("DEST is SOURCE: existing files are never changed")
        if dest.resolve().is_relative_to(source.resolve()):
            parser.error("DEST is inside SOURCE: choose a DEST outside it")
        if dest.exists() and not (args.force or args.dry_run):
            parser.error(f"{dest} exists: use --force to overwrite it")
        for relative in walk(source, args.exclude):
            target = dest / relative
            if exports(relative, args.to):
                target = target.with_suffix(".py")
            handle_file(
                source / relative,
                target,
                relative.as_posix(),
                args,
                options,
                summary,
                False,
            )
        shown_dest = dest

    totals = []
    if summary.exported or args.to == "py":
        totals.append(plural(summary.exported, "notebook") + " exported")
    if summary.converted or summary.unchanged or args.to == "ipynb":
        totals.append(plural(summary.converted, "file") + " converted")
        totals.append(f"{summary.unchanged} already fine")
    if source.is_dir() and summary.copied:
        totals.append(f"{summary.copied} copied")
    if summary.skipped:
        totals.append(f"{summary.skipped} skipped")
    totals.append(plural(summary.warnings, "warning"))
    if summary.failed:
        totals.append(f"{summary.failed} failed")
    verb = "Would write" if args.dry_run else "Wrote"
    print(f"\n{', '.join(totals)}.")
    if summary.written or summary.copied:
        print(f"{verb} {shown_dest}")
    if args.report:
        heading = f"# hc-migrate: {source}\n\n{', '.join(totals)}.\n\n"
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(heading + "\n".join(summary.report), encoding="utf-8")
        print(f"Report: {args.report}")
    return 1 if summary.failed else 0


if __name__ == "__main__":
    sys.exit(main())

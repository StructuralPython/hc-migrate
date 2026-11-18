"""
The ``handcalcs-migrate`` command.

    handcalcs-migrate calc.ipynb               # writes calc_v2.ipynb
    handcalcs-migrate projects/ -o projects-v2 # converts a copy of the tree

The source is never changed.
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
from .notebook import FileResult, Options, convert_notebook, convert_script

CONVERTIBLE = (".ipynb", ".py")
DEFAULT_EXCLUDES = (".git", ".ipynb_checkpoints", "__pycache__", ".venv", ".DS_Store")

DESCRIPTION = """\
Convert Jupyter notebooks (.ipynb) and Python files (.py) written for
handcalcs v1 to handcalcs v2.

SOURCE is a file or a directory. A file is written next to it with "_v2" added
to its name; a directory is copied, with every file in it, to "<SOURCE>_v2",
and the notebooks and Python files in the copy are converted. The source is
never changed. Files that don't use handcalcs are copied as they are.
"""

EPILOG = f"""\
examples:
  handcalcs-migrate beam.ipynb                  writes beam_v2.ipynb
  handcalcs-migrate beam.ipynb -o new/beam.ipynb
  handcalcs-migrate calcs/                      writes calcs_v2/
  handcalcs-migrate calcs/ -o calcs-v2 --report report.md
  handcalcs-migrate calcs/ --dry-run            only reports what would change

What changes, and what to check by hand afterwards, is reported for each file.
The v1 to v2 guide: {GUIDE}
"""


@dataclass
class Summary:
    converted: int = 0
    unchanged: int = 0
    copied: int = 0
    failed: int = 0
    warnings: int = 0
    report: list[str] = field(default_factory=list)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="handcalcs-migrate",
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
        help='where to write (default: SOURCE with "_v2" added)',
    )
    parser.add_argument(
        "-f", "--force", action="store_true", help="overwrite DEST if it exists"
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="report what would change without writing anything",
    )
    parser.add_argument(
        "--report",
        metavar="FILE",
        type=Path,
        help="also write the report to FILE (Markdown)",
    )
    parser.add_argument(
        "--keep-v1-precision",
        action="store_true",
        help="show numbers with 3 decimal places where v1 used its default "
        "(v2's default is 5 significant figures)",
    )
    parser.add_argument(
        "--v1-names",
        action="store_true",
        help="keep v1's nested subscripts (x_a_b) and Greek names (phiM) with "
        "set_option calls",
    )
    parser.add_argument(
        "--clear-outputs",
        action="store_true",
        help="clear the outputs of converted cells (they show the v1 render)",
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
        help="in a directory, write only notebooks and Python files, not other files",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="report only files with warnings"
    )
    parser.add_argument(
        "-V", "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser


def default_output(source: Path) -> Path:
    if source.is_dir():
        return source.with_name(source.resolve().name + "_v2")
    return source.with_name(f"{source.stem}_v2{source.suffix}")


def convert_file(path: Path, options: Options) -> FileResult:
    text = path.read_text(encoding="utf-8")
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
    options: Options,
    summary: Summary,
) -> None:
    """Convert (or copy) one file and record it in the summary."""
    if source.suffix not in CONVERTIBLE:
        if not args.only_converted:
            if not args.dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
            summary.copied += 1
        return
    try:
        result = convert_file(source, options)
    except (ValueError, UnicodeDecodeError, OSError) as error:
        summary.failed += 1
        print(f"FAILED  {shown_as}: {error}; copied unchanged", file=sys.stderr)
        summary.report.append(f"## {shown_as}\n\nFailed: {error}. Copied unchanged.\n")
        if not args.dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
        return
    if not args.dry_run:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if result.changed:
            dest.write_text(result.text, encoding="utf-8", newline="")
            shutil.copystat(source, dest)
        else:
            shutil.copy2(source, dest)
    if not result.uses_handcalcs:
        summary.copied += 1
        return
    warnings = result.warnings
    summary.warnings += len(warnings)
    if result.changed:
        summary.converted += 1
    else:
        summary.unchanged += 1
    changes = [(w, n) for w, n in result.notes if n.level == "change"]
    status = "converted" if result.changed else "no changes needed"
    line = f"{status:<17} {shown_as}"
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
    source: Path = args.source
    if not source.exists():
        parser.error(f"{source}: no such file or directory")
    if source.is_file() and source.suffix not in CONVERTIBLE:
        parser.error(f"{source}: not a notebook (.ipynb) or Python file (.py)")
    dest: Path = args.output or default_output(source)
    if dest.resolve() == source.resolve():
        parser.error(
            "DEST is SOURCE: the source is never changed, so give another DEST"
        )
    if source.is_dir() and dest.resolve().is_relative_to(source.resolve()):
        parser.error("DEST is inside SOURCE: choose a DEST outside it")
    if dest.exists() and not (args.force or args.dry_run):
        parser.error(f"{dest} exists: use --force to overwrite it")
    options = Options(
        keep_v1_precision=args.keep_v1_precision,
        v1_names=args.v1_names,
        clear_outputs=args.clear_outputs,
    )

    summary = Summary()
    if source.is_file():
        handle_file(source, dest, str(source), args, options, summary)
    else:
        for relative in walk(source, args.exclude):
            handle_file(
                source / relative,
                dest / relative,
                relative.as_posix(),
                args,
                options,
                summary,
            )

    totals = [
        plural(summary.converted, "file") + " converted",
        f"{summary.unchanged} already fine",
        plural(summary.warnings, "warning"),
    ]
    if source.is_dir():
        totals.insert(2, f"{summary.copied} copied")
    if summary.failed:
        totals.append(f"{summary.failed} failed")
    verb = "Would write" if args.dry_run else "Wrote"
    print(f"\n{', '.join(totals)}.")
    if summary.converted or summary.copied or summary.unchanged:
        print(f"{verb} {dest}")
    if args.report:
        heading = f"# handcalcs v1 to v2: {source}\n\n{', '.join(totals)}.\n\n"
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(heading + "\n".join(summary.report), encoding="utf-8")
        print(f"Report: {args.report}")
    return 1 if summary.failed else 0


if __name__ == "__main__":
    sys.exit(main())

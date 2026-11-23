# Command-line options

```text
hc-migrate SOURCE [options]
```

`SOURCE` is a notebook (`.ipynb`), a Python file (`.py`) or a folder.

`-o`, `--output DEST`
: Where to write: a file, or a folder for a tree. The default is next to
  `SOURCE`: `beam.py` for `beam.ipynb`, `beam_v2.ipynb` with `--to nb`,
  `beam_v2.py` for a v1 `beam.py`. For a folder, a script next to each notebook,
  or `<folder>_v2` with `--to nb`.

`--to py`, `--to nb`
: `py` (the default): notebooks become handcalcs v2 scripts. `nb`: notebooks
  written for v1 are converted to v2 and stay notebooks.

`--from auto`, `--from v1`, `--from v2`
: The handcalcs the source was written for. `auto` (the default) tells from the
  source, and takes v2 when nothing tells.

`-f`, `--force`, `--overwrite`
: Overwrite files (or `DEST`) that exist.

`-n`, `--dry-run`
: Report what would be written, and write nothing.

`--report FILE`
: Also write the report to `FILE`, as Markdown.

`--show-code`
: Scripts: show the code cells that the notebook didn't render.

`--no-black`
: Scripts: don't format them with black.

`--keep-v1-precision`
: v1: use 3 decimal places where v1 used its default (v2's default is 5
  significant figures).

`--v1-names`
: v1: keep v1's nested subscripts and Greek names.

`--clear-outputs`
: `--to nb`: clear the outputs of converted cells.

`--exclude PATTERN`
: Skip matching files and folders. Can be given more than once.

`--only-converted`
: With a folder `DEST`, write only the notebooks and Python files.

`-q`, `--quiet`
: Report only the files with warnings.

`-V`, `--version`
: Show the version and exit.

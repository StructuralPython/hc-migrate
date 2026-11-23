# hc-migrate

Turn Jupyter notebooks into [handcalcs](https://github.com/connorferster/handcalcs)
v2 scripts, ready to render or publish, and bring calculations written for
handcalcs v1 up to v2 on the way.

```console
$ hc-migrate calcs/ -o scripts --report report.md
exported          Concrete/Basic Beam Shear.ipynb -> Basic Beam Shear.py  (5 changes, 0 warnings)
exported          Wood/Nails in single shear.ipynb -> Nails in single shear.py  (15 changes, 2 warnings)
...
6 notebooks exported, 6 warnings.
Wrote scripts
Report: report.md
```

A script renders as its notebook showed (with `handcalcs beam.py`,
`HandCalcs(...)(path)` or YMPrint's `_hc` block):

| In the notebook | In the script |
|---|---|
| A Markdown cell | Comment lines: prose, and headings at the same level |
| A `%%render` cell | Its lines; settings its commands changed are set back after it |
| Any other code cell | Its lines between `# hc: -i` and `# hc: -s`: run, not shown (`--show-code` shows them) |
| `%render` lines, `display(Markdown(f"..."))`, calls to `@handcalc(display=True)` functions | Shown |
| Magics, `!` commands, front matter | Dropped |

A notebook written for handcalcs v1 is converted to v2 first; v1 or v2 is told
from the source (`--from v1|v2` decides). To keep a v1 notebook a notebook,
converted to v2, use `--to ipynb`:

```console
$ hc-migrate beam.ipynb --to ipynb
converted         beam.ipynb  (6 changes, 0 warnings)

1 file converted, 0 already fine, 0 warnings.
Wrote beam_v2.ipynb
```

**Existing files are never changed.** A script is written next to its notebook
(or under `-o DEST`); a converted notebook or Python file gets `_v2` in its
name, and a folder converted with `--to ipynb` is copied to `<folder>_v2`.

hc-migrate joins two earlier tools, handcalcs-migrate and nb_pyexporter.

## Install

hc-migrate needs Python 3.11 or later (and black, which comes with it).

```console
$ pipx install hc-migrate        # or: uv tool install hc-migrate
$ uvx hc-migrate calcs/          # or run it once, without installing
```

The scripts and converted notebooks need handcalcs 2.0.
`pip install "hc-migrate[nbconvert]"` adds `jupyter nbconvert --to hcpy`.

## What it converts from v1

| handcalcs v1 | handcalcs v2 |
|---|---|
| `import handcalcs.render`, `%load_ext handcalcs.render` | `import handcalcs` |
| `from handcalcs.decorator import handcalc` | `from handcalcs import handcalc` |
| `%%render 2` | `%%render` with `# hc: -f .2f` |
| `%%render sci_not`, `%%render 3 sci_not` | `# hc: -f .3e` |
| `%%render long` | `# hc: -m` |
| `%%render params` | `# hc: -g` above each run of assignments (a parameter grid) |
| `%%render symbolic` | `# hc: mode = "ass sym"` |
| `%%render short` | `%%render` (the default) |
| `%%tex` (printed the LaTeX source) | `%%source latex` (prints it in v2) |
| `%%render sympy` | `# hc: -y`: a `name = name` line whose right-hand name holds a SymPy expression runs as that expression |
| `## text` between equations | `# text` (in v2, `##` is a heading) |
| a `# comment` line (v1 didn't show it) | the same comment, wrapped in `# hc: -i` / `# hc: -s` so it stays hidden |
| `x = 1  # ignore` | `x = 1  # hc: -i` |
| `@handcalc(override="long", precision=2)` | `@handcalc(LatexRenderer(), render_context={"format_code": ".2f", "multiline": True})` |
| `@handcalc(jupyter_display=True)` | `@handcalc(LatexRenderer(), display=True)` |
| a decorated function with a docstring | adds `docstring=False` (v1 didn't render docstrings) |
| `latex, value = f(...)` for a v1-decorated `f` | `value, latex = f(...)` (v2 returns the value first) |
| `set_option("display_precision", 2)` | `set_option("format_code", ".2f")` |
| `set_option("param_columns", 4)` | `set_option("param_cols", 4)` |
| options v2 removed (`latex_block_start`, `custom_symbols`, ...) | commented out, with the reason |

v1's `%%render` arguments are read exactly as v1 read them, including its
habit of accepting part of a word (`%%render param` is `params`).

## What it asks you to check

Some v1 code has no direct v2 equivalent. It is converted as far as it can be,
and listed under **warnings** (in the terminal and in `--report`):

- `@handcalc(left=..., right=...)` and `@handcalc(record=True)`.
- Uses of a decorated function's result other than `latex, value = f(...)`:
  v1 returned `(latex, value)` and v2 returns `(value, latex)`.
- `custom_symbols`, `custom_brackets`, `greek_exclusions` and other removed
  options.

Names also render a little differently in v2: `x_a_b` is x<sub>a,b</sub> (not
nested), and `phiM` is φM. `--v1-names` keeps the v1 look.

## Options

```text
-o, --output DEST     where to write: a file, or a folder for a tree
--to {py,ipynb}       py: notebooks become v2 scripts (default);
                      ipynb: v1 notebooks are converted and stay notebooks
--from {auto,v1,v2}   the handcalcs the source was written for (default: auto)
-f, --force           overwrite files (or DEST) that exist (also --overwrite)
-n, --dry-run         report what would be written, and write nothing
--report FILE         also write the report to FILE (Markdown)
--show-code           scripts: show the code cells the notebook didn't render
--no-black            scripts: don't format with black
--keep-v1-precision   v1: 3 decimal places where v1 used its default
                      (v2's default is 5 significant figures)
--v1-names            v1: keep v1's nested subscripts and Greek names
--clear-outputs       --to ipynb: clear the outputs of converted cells
--exclude PATTERN     skip matching files and folders (repeatable)
--only-converted      with a folder DEST, write only notebooks and Python files
-q, --quiet           report only files with warnings
```

`.git`, `.ipynb_checkpoints`, `__pycache__` and `.venv` are always skipped.
`python -m hc_migrate` is the same command.

See the handcalcs guide,
[Coming from handcalcs v1](https://handcalcs.structuralpython.com/getting-started/migrating-from-v1.html),
for everything that changed.

## Development

```console
$ uv run --group test pytest
```

The tests convert a v1 notebook and run the result with handcalcs v2 in an
IPython shell, so every converted cell is checked to work, and render the
script exported from it with handcalcs.

## License

Apache 2.0.

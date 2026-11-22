# nb-pyexporter

One-time conversion utility: turns Jupyter notebooks (e.g. handcalcs calculation
notebooks) into clean plain-Python scripts, for use with `ymprint build` /
handcalcs v2.0.

## What it does

- Strips YAML front matter from the first cell (raw or markdown).
- Unwraps cell magics: `%%render params 2` is dropped and the cell body becomes
  ordinary Python lines. Stacked magics (`%%time` + `%%render`) are all removed.
  Non-Python cell magics (`%%bash`, `%%html`, `%%latex`, ...) are commented out.
- Drops line magics and shell escapes (`%matplotlib inline`, `!pip install ...`).
- Also unwraps any `get_ipython().run_cell_magic(...)` calls already in the source.
- Rewrites handcalcs v1 imports (`import handcalcs.render`,
  `from handcalcs import render`) to the v2.0 form `import handcalcs`.
- Removes `# In[14]:` cell reference comments, the shebang and `# coding:` header.
- Collapses blank lines, then formats with black (if black can't parse the
  result it logs a warning and writes the unformatted script).

Markdown cells are kept as `#` comments, as in nbconvert's stock Python export.

## Usage

```sh
uv sync

# Directory tree -> mirrored tree of .py files
uv run nb-pyexporter path/to/notebooks path/to/output

# In place (.py next to each .ipynb)
uv run nb-pyexporter path/to/notebooks

# Single notebook
uv run nb-pyexporter calc.ipynb calc.py
```

Options: `--overwrite` (existing `.py` files are skipped by default), `--dry-run`,
`--no-black`, `--quiet`. Hidden directories and `.ipynb_checkpoints` are skipped.
Exit code is 1 if any notebook failed to convert.

It is also registered as an nbconvert exporter:

```sh
uv run jupyter nbconvert --to cleanpy calc.ipynb
```

## Tests

```sh
uv run pytest
```

# hc-migrate

Two conversions for Jupyter notebooks and
[handcalcs](https://handcalcs.structuralpython.com/):

1. **`--to nb`**: update notebooks written for handcalcs v1 so they work with
   handcalcs v2. They stay notebooks. See [](converting.md).
2. **`--to py`** (the default): turn notebooks, written for v1 or v2, into
   handcalcs v2 scripts, ready to render or publish. See [](exporting.md).

```console
$ hc-migrate beam.ipynb --to nb --output beam_v2.ipynb
$ hc-migrate beam.ipynb --to py --output beam.py
```

```console
$ hc-migrate beam.ipynb
exported          beam.ipynb -> beam.py  (6 changes, 0 warnings)

1 notebook exported, 0 warnings.
Wrote beam.py
```

The script renders as the notebook showed: the Markdown is prose and headings,
the `%%render` cells are calculations, and the other code runs but isn't shown.
Render it with `handcalcs beam.py`, `HandCalcs(...)(path)` or YMPrint's `_hc`
block.

With `--to py`, a notebook written for handcalcs v1 is converted to v2 first.

**Existing files are never changed.**

```{toctree}
:maxdepth: 2

install
exporting
converting
conversions
checks
options
changelog
```

For everything that changed between v1 and v2, see the handcalcs guide,
[Coming from handcalcs v1](https://handcalcs.structuralpython.com/getting-started/migrating-from-v1.html).

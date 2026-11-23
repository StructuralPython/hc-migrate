# hc-migrate

Turn Jupyter notebooks into [handcalcs](https://handcalcs.structuralpython.com/) v2
scripts, ready to render or publish, and bring calculations written for
handcalcs v1 up to v2 on the way.

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

A notebook written for handcalcs v1 is converted to v2 first. To keep it a
notebook, use `--to ipynb`: the converted copy is written next to it.

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

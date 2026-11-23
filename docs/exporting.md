# Export notebooks as scripts

```console
$ hc-migrate beam.ipynb                  # writes beam.py
$ hc-migrate beam.ipynb -o out/beam.py
$ hc-migrate calcs/                      # a .py next to each notebook
$ hc-migrate calcs/ -o scripts           # a copy of the tree, notebooks as scripts
```

A script that already exists is skipped (for a folder) or an error (for one
notebook) unless you add `-f`.

## What the script holds

handcalcs renders every line of a script, but a notebook showed only its
`%%render` cells and its Markdown. Each kind of cell is written so that the
script renders as the notebook did:

| In the notebook | In the script |
|---|---|
| A Markdown cell | Comment lines (prose). Headings keep their level (`# Title` becomes `## Title`, handcalcs' top level), and paragraphs and list items are kept apart with `# hc: -b`. Images are left out, with a warning. |
| A `%%render` cell | Its lines, without the magic. A comment command on its own line (`# hc: -m`) applied to the rest of the cell, so after the cell the settings it changed are set back (`# hc: multiline = False`). |
| Any other code cell | Its lines between `# hc: -i` and `# hc: -s`: they run, but aren't shown. `--show-code` shows them. |
| A `%render` line in a code cell | Shown. |
| `display(Markdown(f"..."))` | Comment lines, with the values in `{{ }}` for handcalcs to fill. |
| A call to a `@handcalc(..., display=True)` function | Shown with its result; the decorator is removed (a script can't show the function's working). |
| Line magics, `!` commands | Dropped. A cell magic that isn't Python (`%%bash`) is commented out. |
| Front matter in the first cell, raw cells | Dropped. |

The script is checked to be valid Python and formatted with black
(`--no-black` leaves it as written).

## Notebooks written for handcalcs v1

hc-migrate tells a v1 notebook from a v2 one (v1 has to `import handcalcs.render`;
its `%%render` arguments, `%%tex` and options give it away too) and converts a v1
notebook to v2 before exporting it, as [`--to ipynb`](converting.md) would. When
nothing tells, it's treated as v2 and the report says so; `--from v1` or
`--from v2` decides.

## As an nbconvert exporter

With `pip install "hc-migrate[nbconvert]"`, Jupyter can export the same script:

```console
$ jupyter nbconvert --to hcpy beam.ipynb
```

It also appears as "handcalcs v2 script" in Jupyter's *Save and Export As* menu.

# Install

hc-migrate needs Python 3.11 or later. It reads and rewrites your files as
text, so it doesn't need handcalcs itself; black, which formats the scripts,
comes with it.

Install it as a command-line tool:

```console
$ pipx install hc-migrate
```

or with uv:

```console
$ uv tool install hc-migrate
```

Or run it once, without installing:

```console
$ uvx hc-migrate calcs/
```

`python -m hc_migrate` is the same command as `hc-migrate`. For
`jupyter nbconvert --to hcpy`, install the `nbconvert` extra:
`pip install "hc-migrate[nbconvert]"`.

The scripts and converted notebooks need **handcalcs 2.0**:

```console
$ pip install --upgrade handcalcs
```

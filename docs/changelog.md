# Changelog

## 0.2.0 (unreleased)

The first release of hc-migrate, which joins two tools: handcalcs-migrate
(handcalcs v1 to v2) and nb_pyexporter (notebooks to scripts).

- **Notebooks become handcalcs v2 scripts** (`hc-migrate beam.ipynb` writes
  `beam.py`), rendering as the notebook showed: Markdown as prose and headings,
  `%%render` cells as calculations, other code hidden. A notebook written for
  handcalcs v1 is converted to v2 on the way. See [](exporting.md).
- **v1 to v2 conversion** of notebooks (`--to ipynb`), Python files and folders of
  them, including `%%tex` to `%%source latex` and `%%render sympy` to `# hc: -y`.
- v1 or v2 is told from the source (`--from` decides).
- `jupyter nbconvert --to hcpy` with the `nbconvert` extra.

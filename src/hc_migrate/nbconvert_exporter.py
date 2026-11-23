"""
The export as an nbconvert exporter: ``jupyter nbconvert --to hcpy calc.ipynb``
(with ``pip install "hc-migrate[nbconvert]"``). It writes what ``hc-migrate``
writes for a notebook (see ``export``).
"""

from __future__ import annotations

from nbconvert.exporters import Exporter
from traitlets import Bool, Unicode

from .export import ExportOptions, export_notebook


class HandcalcsScriptExporter(Exporter):
    """Export a notebook as a handcalcs v2 script (see ``hc_migrate.export``)."""

    export_from_notebook = "handcalcs v2 script"
    output_mimetype = "text/x-python"

    source = Unicode(
        "auto", help='The handcalcs the notebook was written for: "v1", "v2" or "auto".'
    ).tag(config=True)
    show_code = Bool(False, help="Show the code cells that weren't rendered.").tag(
        config=True
    )
    use_black = Bool(True, help="Format the script with black.").tag(config=True)

    def _file_extension_default(self):
        return ".py"

    def from_notebook_node(self, nb, resources=None, **kw):
        nb_copy, resources = super().from_notebook_node(nb, resources, **kw)
        name = (resources or {}).get("metadata", {}).get("name", "<notebook>")
        options = ExportOptions(
            source=self.source, show_code=self.show_code, black=self.use_black
        )
        return export_notebook(dict(nb_copy), options, name).text, resources

"""nbconvert exporter producing clean, plain Python scripts from notebooks."""

from __future__ import annotations

import copy

from nbconvert.exporters import PythonExporter
from traitlets import Bool

from .transforms import clean_notebook, postprocess


class CleanPythonExporter(PythonExporter):
    """Export a notebook to a plain Python script.

    Compared with the stock ``PythonExporter`` this:

    * strips YAML front matter from the first cell,
    * unwraps cell magics (``%%render params`` ...) so the cell body becomes
      ordinary Python lines, and drops line magics / shell escapes,
    * removes ``# In[N]:`` cell reference comments,
    * removes the shebang and ``# coding`` header,
    * collapses excess whitespace and formats the result with black.

    Usable directly or via ``jupyter nbconvert --to cleanpy``.
    """

    export_from_notebook = "Clean Python Script"

    exclude_input_prompt = Bool(True, help="Omit `# In[N]:` comments.").tag(config=True)
    use_black = Bool(True, help="Format the output with black.").tag(config=True)

    def default_filters(self):
        # Magics are already stripped in `clean_notebook`, so IPython's syntax
        # transform is unnecessary; making it a no-op keeps output identical
        # whether or not IPython is installed (and silences its warning).
        for name, func in super().default_filters():
            yield name, (lambda s: s) if name == "ipython2python" else func

    def from_notebook_node(self, nb, resources=None, **kw):
        nb = copy.deepcopy(nb)
        clean_notebook(nb)
        output, resources = super().from_notebook_node(nb, resources, **kw)
        name = (resources or {}).get("metadata", {}).get("name", "<notebook>")
        return postprocess(output, use_black=self.use_black, source_name=name), resources

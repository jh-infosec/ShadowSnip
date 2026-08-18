"""Double-clickable launcher: runs ShadowSnip with no console window.

For people who would rather not build the .exe. Put a shortcut to this file in
shell:startup to run ShadowSnip at login. Because the extension is .pyw it is
handled by pythonw.exe, so no PowerShell window appears.
"""

import runpy

runpy.run_module("main", run_name="__main__")

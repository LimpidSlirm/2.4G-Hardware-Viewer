"""Creation flags that keep Windows helper processes from flashing a console."""

from __future__ import annotations

import subprocess

# The app runs under pythonw.exe, which owns no console. A child console
# program such as powershell.exe would then allocate a brand new visible
# console window on every call. CREATE_NO_WINDOW suppresses that allocation.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

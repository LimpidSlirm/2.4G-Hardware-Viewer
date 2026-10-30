"""Launcher used by the Windows startup entry."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from app.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

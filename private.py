"""Compatibility launcher for the Private Search CLI.

The implementation lives in ``src/private_search/search.py``.
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from private_search.search import main


if __name__ == "__main__":
    main()

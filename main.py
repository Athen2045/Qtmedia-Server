"""Compatibility launcher for the direct-link downloader.

The implementation lives in ``src/private_search/downloader.py``.
"""

import sys
from pathlib import Path


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
    from private_search.downloader import main as downloader_main

    downloader_main()

if __name__ == "__main__":
    main()

"""Launch the search CLI from a source checkout.

The implementation lives in ``src/private_search/search.py``.
"""

import sys
from pathlib import Path


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
    from private_search.search import main as search_main

    search_main()


if __name__ == "__main__":
    main()

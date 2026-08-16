"""Start the unified interactive terminal menu from a source checkout."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from private_search.app.cli import interactive_menu


def main() -> None:
    interactive_menu()


if __name__ == "__main__":
    main()

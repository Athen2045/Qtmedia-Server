"""Start THEIA from a source checkout."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from private_search.app.chat_ui import interactive_chat


def main() -> None:
    interactive_chat()


if __name__ == "__main__":
    main()

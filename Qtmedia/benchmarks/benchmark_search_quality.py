"""Deterministic local benchmark for title ranking; no network access required."""

from __future__ import annotations

import time

from qtmedia.search.quality import relevance_score


def main() -> None:
    query = "Skylar Vox PMV"
    titles = [
        f"Unrelated compilation {index}"
        for index in range(9_999)
    ] + ["Skylar Vox PMV"]
    started = time.perf_counter()
    ranked = sorted(titles, key=lambda title: relevance_score(title, query), reverse=True)
    elapsed = time.perf_counter() - started
    print(f"ranked={len(ranked)} top={ranked[0]!r} seconds={elapsed:.6f}")


if __name__ == "__main__":
    main()


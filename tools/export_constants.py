"""Generate the browser engine's constants from constants.py.

The web app reimplements the engine in JavaScript so it can compute charts and
indices for any rules on a phone with no server. Two implementations of the same
model is a standing invitation to drift, so the empirical numbers are not
retyped: they are emitted from the Python module that owns them.

Run via `python -m tools.export_constants`; `tests/test_web_engine.py` fails if
the generated file is out of date.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bjtoolkit import constants as C  # noqa: E402

HEADER = """// GENERATED FILE -- do not edit.
// Emitted from src/bjtoolkit/constants.py by tools/export_constants.py so the
// browser engine and the Python engine cannot disagree about the numbers.
// Regenerate with: python -m tools.export_constants
"""

EXPORTED = (
    "BASELINE_8D", "HITS_SOFT_17", "DOUBLE_9_TO_11", "DOUBLE_10_11",
    "NO_DAS", "RESPLIT_ACES", "SPLIT_TO_2_HANDS", "SPLIT_TO_3_HANDS",
    "LATE_SURRENDER_VS_10", "LATE_SURRENDER_VS_9_10", "LATE_SURRENDER_ALL",
    "EARLY_SURRENDER_VS_10", "EARLY_SURRENDER_ALL", "BJ_PAYS_6_5",
    "BJ_PAYS_7_5", "BJ_PAYS_1_1", "ENHC_ORIGINAL_BET_ONLY",
    "ENHC_ALL_BETS_LOST", "HILO_SLOPE", "HAND_VARIANCE",
    "HAND_VARIANCE_TC_SLOPE", "CARDS_PER_HAND",
)


def _js_string(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _estimate(e: C.Estimate) -> str:
    return (
        f"{{ value: {e.value!r}, low: {e.low!r}, high: {e.high!r}, "
        f"source: {_js_string(e.source)} }}"
    )


def render() -> str:
    lines = [HEADER, "export const ESTIMATES = {"]
    for name, est in sorted(C.ALL_ESTIMATES.items()):
        lines.append(f"  {name}: {_estimate(est)},")
    lines.append("};")
    lines.append("")
    lines.append("export const DECK_EFFECT = {")
    for decks, est in sorted(C.DECK_EFFECT.items()):
        lines.append(f"  {decks}: {_estimate(est)},")
    lines.append("};")
    lines.append("")
    for name in EXPORTED:
        lines.append(f"export const {name} = ESTIMATES.{name};")
    lines.append("")
    return "\n".join(lines)


def target() -> Path:
    root = Path(__file__).resolve().parent.parent
    return root / "web" / "src" / "engine" / "constants.js"


def main() -> int:
    path = target()
    path.parent.mkdir(parents=True, exist_ok=True)
    new = render()
    if path.exists() and path.read_text() == new:
        print(f"{path} already current")
        return 0
    path.write_text(new)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

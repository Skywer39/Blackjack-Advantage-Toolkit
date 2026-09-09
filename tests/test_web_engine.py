"""The browser engine is a second implementation of the same model.

Two implementations drift. These tests are the defence: the generated constants
must be current, and the JavaScript must reproduce the Python's answers exactly
on a fixture set covering edges, dealer distributions, action EVs, whole charts
and the risk arithmetic.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "conformance.json"
CONFORMANCE = ROOT / "web" / "tests" / "conformance.test.mjs"

node = shutil.which("node")
needs_node = pytest.mark.skipif(node is None, reason="node is not installed")


def test_generated_constants_are_current():
    """constants.js is emitted from constants.py; a stale copy means the browser
    is quoting numbers the Python engine no longer believes."""
    from tools.export_constants import render, target

    path = target()
    assert path.exists(), "run: python -m tools.export_constants"
    assert path.read_text() == render(), (
        "web/src/engine/constants.js is out of date -- "
        "run: python -m tools.export_constants"
    )


def test_constants_file_is_marked_generated():
    from tools.export_constants import target

    assert "GENERATED FILE" in target().read_text()


def test_fixtures_exist_and_cover_the_engine():
    assert FIXTURES.exists(), "run: python -m tools.export_fixtures"
    fx = json.loads(FIXTURES.read_text())
    assert set(fx) >= {"edges", "dealer", "charts", "actionEvs", "risk",
                       "insurance"}
    assert len(fx["charts"]) >= 3
    # A whole chart is 340 cells; anything less is not a real comparison.
    for name, chart in fx["charts"].items():
        assert len(chart) == 340, name
    assert len(fx["actionEvs"]) >= 8
    assert len(fx["risk"]["cases"]) >= 8


def test_fixtures_are_current():
    """Regenerating must be a no-op. If it is not, the Python engine has moved
    and the JS has not been re-checked against it."""
    from tools.export_fixtures import fixtures

    on_disk = json.loads(FIXTURES.read_text())
    assert on_disk == json.loads(json.dumps(fixtures())), (
        "conformance fixtures are stale -- run: python -m tools.export_fixtures"
    )


@needs_node
@pytest.mark.slow
def test_browser_engine_matches_python():
    """The headline: run the JS engine and compare it against Python's answers."""
    result = subprocess.run(
        [node, str(CONFORMANCE)], capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "matches the Python engine" in result.stdout


@needs_node
def test_browser_engine_loads_and_agrees_on_the_edges():
    """A cheap subset of the conformance run, kept in the fast suite so a broken
    port is caught in seconds rather than at the end of a slow run."""
    script = """
    import { PRESETS, baseEdge } from "./web/src/engine/rules.js";
    const out = {};
    for (const [k, r] of Object.entries(PRESETS)) out[k] = baseEdge(r);
    console.log(JSON.stringify(out));
    """
    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True, text=True, cwd=ROOT, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    got = json.loads(result.stdout)
    want = json.loads(FIXTURES.read_text())["edges"]
    for name, expected in want.items():
        assert got[name] == pytest.approx(expected["edge"], abs=1e-12), name

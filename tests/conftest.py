import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Point the distribution cache at a scratch directory before anything imports it.
# Otherwise a test that passes --regen with a small shoe count overwrites the
# repository's cached distributions with a noisier one, and every later run --
# including the numbers quoted in the README -- silently shifts.
_CACHE = tempfile.TemporaryDirectory()
os.environ["BJTOOLKIT_CACHE_DIR"] = _CACHE.name

# These imports must follow the sys.path and cache-directory setup above, so
# the usual "imports at top of file" rule does not apply here.
import pytest  # noqa: E402

from bjtoolkit.frequency import simulate_tc_distribution  # noqa: E402
from bjtoolkit.rules import get_preset  # noqa: E402


@pytest.fixture(scope="session")
def rules():
    return get_preset("ambassador")


@pytest.fixture(scope="session")
def dist(rules):
    # Small and seeded: these tests assert on structure, not on the 4th decimal.
    return simulate_tc_distribution(rules, n_shoes=4000, seed=99)

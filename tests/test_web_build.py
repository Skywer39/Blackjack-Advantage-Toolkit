"""The single-file build is what ships to a phone, so it gets tested too."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
node = shutil.which("node")
needs_node = pytest.mark.skipif(node is None, reason="node is not installed")


@pytest.fixture(scope="module")
def bundle():
    from tools.build_web import build
    return build()


def test_bundle_is_self_contained(bundle):
    """No module imports may survive: a bundled page has no server to fetch from."""
    assert 'src="./src/app.js"' not in bundle
    assert not re.search(r'^\s*import\s+.*from\s+["\']\./', bundle, re.MULTILINE)
    assert not re.search(r'^\s*export\s+(const|function|class)', bundle, re.MULTILINE)


def test_bundle_only_reaches_out_for_fonts(bundle):
    """Everything else must be inline -- the artifact CSP blocks other hosts,
    and a page you saved for the casino floor has no network at all."""
    urls = re.findall(r'https?://[^\s"\')]+', bundle)
    for url in urls:
        # The SVG namespace is an XML identifier, not a fetch -- nothing is
        # requested from w3.org.
        if url.startswith("http://www.w3.org/"):
            continue
        assert url.startswith("https://fonts.g"), url


def test_bundle_carries_the_whole_engine(bundle):
    for marker in ("dealerOutcomes", "basicStrategy", "simulateTcDistribution",
                   "bankrollForRor", "kellyForRor", "evSplit", "insuranceIndex"):
        assert marker in bundle, marker


def test_bundle_has_no_duplicate_top_level_names():
    """The bundler concatenates modules, so a name defined twice would silently
    shadow. This is the check that makes that dumb approach safe."""
    from tools.build_web import bundle_js

    _, by_module = bundle_js()
    seen: dict[str, str] = {}
    clashes = []
    for module, names in by_module.items():
        for name in names:
            if name in seen:
                clashes.append(f"{name}: {seen[name]} and {module}")
            seen[name] = module
    assert not clashes, "duplicate top-level names: " + "; ".join(clashes)


def test_bundle_declares_a_title_and_both_themes(bundle):
    assert "<title>" in bundle
    assert 'prefers-color-scheme: dark' in bundle
    assert ':root[data-theme="dark"]' in bundle
    assert ':root:not([data-theme="light"])' in bundle


def test_bundle_has_no_doctype_or_body_tag(bundle):
    """The artifact host supplies the document skeleton."""
    lowered = bundle.lower()
    for tag in ("<!doctype", "<html", "<head>", "<body"):
        assert tag not in lowered, tag


@needs_node
def test_bundle_is_valid_javascript(tmp_path, bundle):
    match = re.search(r'<script type="module">(.*)</script>', bundle, re.S)
    assert match, "no inline module found in the bundle"
    js = tmp_path / "bundle.mjs"
    js.write_text(match.group(1))
    result = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_committed_bundle_is_current(bundle):
    dist = ROOT / "web" / "dist" / "index.html"
    assert dist.exists(), "run: python -m tools.build_web"
    assert dist.read_text() == bundle, (
        "web/dist/index.html is stale -- run: python -m tools.build_web"
    )

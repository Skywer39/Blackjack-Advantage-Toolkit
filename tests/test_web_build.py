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
                   "bankrollForRor", "kellyForRor", "evSplit", "insuranceIndex",
                   "countQuestion", "trueCountQuestion", "deviationQuestion",
                   "checkAnswer", "loadProgress"):
        assert marker in bundle, marker


def test_every_engine_module_is_bundled():
    """A module left out of MODULES vanishes from the bundle silently -- the app
    then renders a blank panel with a ReferenceError in the console. Adding an
    engine file must mean adding it here."""
    from tools.build_web import MODULES, WEB

    on_disk = {f"src/engine/{p.name}" for p in (WEB / "src" / "engine").glob("*.js")}
    listed = {m for m in MODULES if m.startswith("src/engine/")}
    assert on_disk == listed, f"not bundled: {sorted(on_disk - listed)}"


def test_app_symbols_resolve_against_the_bundle():
    """Every capitalised import the app pulls from the engine must be defined
    somewhere in the bundle."""
    from tools.build_web import WEB, bundle_js

    _, by_module = bundle_js()
    defined = set().union(*by_module.values())
    app = (WEB / "src" / "app.js").read_text()
    import re as _re
    imported = set()
    for block in _re.findall(r"import\s*\{([^}]*)\}\s*from\s*[\"']\./", app):
        for name in block.split(","):
            name = name.strip().split(" as ")[0].strip()
            if name:
                imported.add(name)
    missing = sorted(imported - defined)
    assert not missing, f"app.js imports names the bundle does not define: {missing}"


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


def _theme_blocks(css: str) -> list[tuple[str, str]]:
    """Every @media (prefers-color-scheme) and [data-theme] block body."""
    import re as _re

    blocks = []
    for m in _re.finditer(r"@media\s*\(prefers-color-scheme[^)]*\)\s*\{", css):
        depth = 1
        i = m.end()
        while i < len(css) and depth:
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        blocks.append(("prefers-color-scheme", css[m.end():i - 1]))
    for m in _re.finditer(r':root\[data-theme="[^"]+"\]\s*\{([^}]*)\}', css):
        blocks.append(("data-theme", m.group(1)))
    return blocks


def test_theme_blocks_only_define_tokens(bundle):
    """Components must be styled through tokens, never inside a theme block.

    A per-theme rule on a component silently outranks its own modifier: an
    override on `.btn` beat `.btn.ghost` and made every ghost button invisible
    in BOTH themes -- white on the light ground, near-black on the dark one.
    Keeping theme blocks to custom properties makes that impossible.
    """
    import re as _re

    offenders = []
    for kind, body in _theme_blocks(bundle):
        # Strip nested :root{...} groups, which are token definitions.
        inner = _re.sub(r":root[^{]*\{[^}]*\}", "", body)
        for decl in _re.findall(r"([a-zA-Z-]+)\s*:", inner):
            if not decl.startswith("--"):
                offenders.append(f"{kind}: {decl}")
    assert not offenders, (
        "theme blocks must only declare custom properties, found: "
        + ", ".join(sorted(set(offenders)))
    )


def test_accent_text_colour_is_a_token(bundle):
    """The colour of text on the accent has to change with the theme, so it is a
    token rather than a literal repeated per theme."""
    assert "--on-accent" in bundle
    assert "color:var(--on-accent)" in bundle.replace(" ", "")


def test_every_token_used_is_defined(bundle):
    """A var() with no definition in the bare :root renders as nothing at all --
    the classic unreadable-artifact bug."""
    import re as _re

    root = _re.search(r":root\s*\{([^}]*)\}", bundle)
    assert root, "no bare :root token block"
    defined = set(_re.findall(r"(--[\w-]+)\s*:", root.group(1)))
    used = set(_re.findall(r"var\((--[\w-]+)", bundle))
    missing = sorted(used - defined)
    assert not missing, f"tokens used but never defined in the bare :root: {missing}"

"""Bundle the web app into one self-contained HTML file.

The source stays as ES modules -- readable, and servable directly by GitHub
Pages. This produces the single-file build, which is what a Claude Artifact
needs and what works from a phone's saved copy with no server at all.

The bundling is deliberately dumb: concatenate the modules in dependency order,
drop the intra-bundle `import` lines and the `export` keywords, and inline the
result. It works because the engine has no duplicate top-level names -- which
`test_web_build.py` checks, so a future collision fails loudly instead of
producing a silently broken page.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

# Dependency order: each module may only use names defined above it.
MODULES = [
    "src/engine/constants.js",
    "src/engine/cards.js",
    "src/engine/rules.js",
    "src/engine/analyzer.js",
    "src/engine/strategy.js",
    "src/engine/frequency.js",
    "src/engine/risk.js",
    "src/engine/trainer.js",
    "src/app.js",
]

IMPORT_RE = re.compile(r"^import\s.*?from\s+[\"'][^\"']+[\"'];\s*$",
                       re.MULTILINE | re.DOTALL)
MULTILINE_IMPORT_RE = re.compile(
    r"^import\s*\{[^}]*\}\s*from\s*[\"'][^\"']+[\"'];\s*$",
    re.MULTILINE,
)
EXPORT_RE = re.compile(r"^export\s+(?=const|let|var|function|class)", re.MULTILINE)


def strip_module(source: str) -> str:
    source = MULTILINE_IMPORT_RE.sub("", source)
    source = IMPORT_RE.sub("", source)
    source = EXPORT_RE.sub("", source)
    source = re.sub(r"^export\s*\{[^}]*\};\s*$", "", source, flags=re.MULTILINE)
    return source.strip()


def top_level_names(source: str) -> set[str]:
    names = set()
    for m in re.finditer(
        r"^(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)",
        source, re.MULTILINE,
    ):
        names.add(m.group(1))
    return names


def bundle_js() -> tuple[str, dict[str, set[str]]]:
    chunks = []
    by_module: dict[str, set[str]] = {}
    for rel in MODULES:
        text = (WEB / rel).read_text()
        stripped = strip_module(text)
        by_module[rel] = top_level_names(stripped)
        chunks.append(f"// ---- {rel} " + "-" * max(0, 60 - len(rel)) + "\n" + stripped)
    return "\n\n".join(chunks), by_module


def build() -> str:
    html = (WEB / "index.html").read_text()
    js, _ = bundle_js()
    marker = '<script type="module" src="./src/app.js"></script>'
    if marker not in html:
        raise SystemExit("could not find the module tag to replace in index.html")
    return html.replace(marker, f'<script type="module">\n{js}\n</script>')


def build_sw(html: str) -> str:
    """The service worker, stamped with a hash of the page it caches.

    Without this a redeploy would keep serving the previous build from cache,
    and a stale bet ramp is worse than none because it still looks current.
    """
    digest = hashlib.sha256(html.encode()).hexdigest()[:12]
    sw = (WEB / "sw.js").read_text()
    if "__BUILD__" not in sw:
        raise SystemExit("sw.js has no __BUILD__ placeholder to stamp")
    return sw.replace("__BUILD__", digest)


def main() -> int:
    out = WEB / "dist"
    out.mkdir(parents=True, exist_ok=True)
    html = build()
    (out / "index.html").write_text(html)
    (out / "sw.js").write_text(build_sw(html))
    shutil.copy2(WEB / "manifest.webmanifest", out / "manifest.webmanifest")
    icons = out / "icons"
    icons.mkdir(exist_ok=True)
    for src in sorted((WEB / "icons").glob("*.png")):
        shutil.copy2(src, icons / src.name)
    n = len(list(icons.glob("*.png")))
    print(f"wrote {out}/ ({len(html) / 1024:.0f} KB page, {n} icons)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

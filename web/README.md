# Ramp &amp; Ruin — the web app

A single self-contained HTML file. No server, no build step at runtime, no
dependencies beyond two Google Fonts. Open it from a file, from GitHub Pages, or
save it to a phone home screen and use it with no signal at all.

## Why it recomputes rather than looks things up

The engine is ported to JavaScript (`src/engine/`), so the app can price **any**
rule set — not just the presets. Change the decks, the surrender rule, the hole
card, and the chart and the indices are recomputed from scratch. A precomputed
bundle would have covered a handful of games and quietly lied about the rest.

Cost of that choice: two implementations of one model, which is a standing
invitation to drift. Two things hold them together.

* `src/engine/constants.js` is **generated** from `src/bjtoolkit/constants.py`
  by `tools/export_constants.py`. The empirical numbers exist in one place.
* `tests/conformance.test.mjs` asserts the JavaScript reproduces the Python's
  answers — edges, dealer distributions, exact action EVs, four complete 340-cell
  charts, and the risk arithmetic — to 1e-9. That is 2,127 checks, and `pytest`
  runs it.

If you change the Python engine and not the JavaScript, the test suite fails.

## Layout

```
web/
  index.html          shell, styles, and the module tag the bundler replaces
  src/engine/*.js     the port: cards, rules, analyzer, strategy, frequency, risk
  src/app.js          the UI
  tests/              the conformance harness
  dist/index.html     the built single file (committed, checked for staleness)
```

## Working on it

```bash
python -m tools.export_constants   # after changing constants.py
python -m tools.build_web          # rebuild dist/index.html
node web/tests/conformance.test.mjs
pytest tests/test_web_engine.py tests/test_web_build.py
```

Serving the source directly works too — the modules are plain ESM:

```bash
python -m http.server -d web 8000   # then open http://localhost:8000
```

## Deploying

`.github/workflows/pages.yml` regenerates the constants, runs the conformance
check and the test suite, rebuilds the bundle and deploys it. Enable it once in
the repository: **Settings → Pages → Source → GitHub Actions**.

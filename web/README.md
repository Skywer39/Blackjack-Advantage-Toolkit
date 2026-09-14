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

## The drill

The third tab is the trainer, ported from `src/bjtoolkit/trainer.py`. Five
drills: card-flash running count (1 to 4 cards per second), true-count
conversion, basic strategy, index plays, and bet sizing off your own ramp.

Questions come from the chart computed for the rules currently set, so you
practise the game you actually sit at. Index plays need a one-off scan of every
cell — about half a minute — which is chunked so the progress bar paints, then
cached in `localStorage` per rule set.

Repetition is weighted toward misses first, then slow answers, bounded so
nothing starves. History lives in `localStorage`: private to your browser, never
sent anywhere, and it survives a republish.

## Offline

A service worker precaches the page, the manifest and the icons, and
cache-firsts the Google Fonts so the typefaces survive too; every `font-family`
declares a real fallback stack, so even an uncached font degrades rather than
breaks. `tests/test_web_build.py` checks the plumbing, and the offline path was
verified by cutting the network and reloading — the app returns and recomputes
the full chart.

The cache name is stamped with a hash of the built page, so a redeploy
invalidates the old one. That matters more here than on most sites: a stale bet
ramp is worse than none, because it still looks current.

Service workers need a real origin, so this applies to the Pages build. The
artifact is served as a lone file with no sibling `sw.js`; registration fails
there and the app carries on, since everything it needs is already inline.

## Layout

```
web/
  index.html          shell, styles, and the module tag the bundler replaces
  src/engine/*.js     the port: cards, rules, analyzer, strategy, frequency, risk
  src/app.js          the UI
  tests/              the conformance harness
  manifest.webmanifest, sw.js, icons/   the offline shell
  dist/               the built site: page, service worker, manifest, icons
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

# site/

The public documentation site: <https://ansarafsar.github.io/what-if/>

Plain HTML, CSS and JavaScript — no framework, no build step, no dependencies.
GitHub Pages serves these three files exactly as they are.

```text
site/
├── index.html    the whole page
├── styles.css    light/dark via prefers-color-scheme
└── script.js     progressive enhancement only
```

## Local preview

```bash
cd site
python -m http.server 8123
# then open http://localhost:8123
```

## Deployment

[`.github/workflows/pages.yml`](../.github/workflows/pages.yml) publishes this
folder on every push to `main` that touches `site/`, and can be run manually via
**Actions → Deploy docs site → Run workflow**.

**One-time setup:** in the repository, go to **Settings → Pages** and set
**Source** to **GitHub Actions**. Until that is done the workflow will fail at
the deploy step — the site cannot publish itself.

## Conventions

- JavaScript is enhancement only: the page is fully readable with it disabled.
  Navigation, copy buttons and scroll-spy degrade to nothing.
- No external requests — no fonts, analytics, or CDN scripts. The page works offline.
- The diagram is inline SVG with `<title>`/`<desc>`, so it survives dark mode and
  screen readers without an image asset.
- Content here mirrors the root `README.md`. When the engine's behaviour changes,
  update both — particularly the reliability table, which documents real retry
  semantics rather than intentions.

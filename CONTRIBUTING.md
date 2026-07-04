# Contributing to the Dispensary Report Card

Thanks for your interest! This scanner grades cannabis dispensary websites
on their e-commerce and marketing setup. The most valuable contribution is
usually a **detection signature** — teaching the scanner to recognize a
platform it doesn't know yet.

## Adding a platform signature

All detection lives in the `SIGS` dict near the top of `report_card.py`.
Each entry maps a key to a list of regex patterns matched (case-insensitively)
against a site's raw HTML:

```python
"klaviyo": [
    r"static\.klaviyo\.com",
    r"/plugins/klaviyo/",
],
```

To add a platform:

1. Find a distinctive marker in the raw page source of a site using it —
   a CDN hostname, script path, or CSS class prefix. Prefer hostnames
   (hardest to false-positive). **Check the raw HTML** (view-source), not
   the rendered DOM — the scanner does not execute JavaScript.
2. Add the entry to `SIGS` under the right section (e-commerce, POS,
   loyalty, email, analytics, reviews).
3. If it's an e-commerce platform, add a tier classification in
   `classify_ecom_platform()` — S (on-domain, e.g. WooCommerce) down to
   C (iframe embeds) — with a short justification comment.
4. If it's a loyalty platform, add it to the ladder in `score_loyalty()`.
5. Add a test in `test_report_card.py` with a minimal HTML fixture that
   proves detection (and, ideally, one showing a near-miss does NOT match —
   false positives are worse than misses).

## Ground rules

- Fixtures must mirror what real sites serve (include `<lastmod>` in sitemap
  fixtures, real CDN hostnames, etc.). Sanitized-fixture bugs have bitten
  this project before.
- Run `python -m pytest test_report_card.py` — everything must pass.
- Scoring changes (weights, point values) need a rationale in the PR
  description; they shift every published grade.

## Bugs and ideas

Open an issue with the site URL (if public), what the scanner said, and what
you expected. Wrong-detection reports with a view-source snippet are gold.

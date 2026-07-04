# Dispensary E-Commerce Report Card

A Python scanner that fetches a dispensary website, detects its SEO + marketing
stack, and grades it across 7 weighted categories. Outputs a shareable HTML
"score page" per site.

---

## For the developer picking this up

**You're reading this because someone is asking you to deploy a Python web
tool to production. Everything you need is in this bundle. Estimated time:
1 hour for the basic deploy, +20 minutes for the optional Google Places
API setup.**

### Stack
- **Language:** Python 3.10+ (tested on 3.10 and 3.11)
- **Web framework:** FastAPI + Uvicorn/Gunicorn
- **HTML parsing:** BeautifulSoup4 + lxml
- **Optional external API:** Google Places API (New) for Google Business Profile checks
- **Deploy target:** Render free tier (zero-config via `render.yaml`)

### Architecture
```
[browser] ─► GET /                       ─► landing page with URL input
[browser] ─► GET /scan?url=...           ─► FastAPI handler
                                              │
                                              ├─ rate limit check (5/hr/IP)
                                              ├─ SSRF protection
                                              │      ↓
                                              ├─ report_card.scan(url, gbp_api_key)
                                              │      │
                                              │      ├─ fetch homepage, robots.txt, sitemap
                                              │      ├─ fetch 1 product page
                                              │      ├─ run all signature detectors
                                              │      ├─ if API key: call Google Places
                                              │      └─ score 7 categories
                                              │
                                              └─ render HTML report
```

No database, no queue, no auth. Each scan is a single synchronous request
that takes 8–30 seconds end-to-end.

### File map
| File | Purpose |
|---|---|
| `report_card.py` | The scanner. Pure logic: signature detection, scoring rubric, HTML/text/JSON rendering. ~1700 lines. Has its own CLI (`python report_card.py https://...`) for testing without the web wrapper. |
| `app.py` | FastAPI wrapper. Adds rate limiting, SSRF protection, landing page, shareable result links. ~400 lines. |
| `test_report_card.py` | 25 unit tests. Run with `python test_report_card.py`. Mocks `fetch()` to avoid hitting the network. |
| `generate_samples.py` | Builds the sample HTML reports under `samples/`. Useful as a working code example. |
| `requirements.txt` | Python deps. |
| `render.yaml` | Render Blueprint config. Render reads this on first deploy. |
| `.gitignore` | Excludes `__pycache__`, `*.pyc`, generated reports. |
| `DEPLOY.md` | The step-by-step deploy walkthrough. Hand this to whoever is doing the deploy if they're following it themselves. |
| `samples/*.html` | Pre-generated reports for stokd.ca, lakecitycannabis.ca, plantlifecannabis.com — illustrative. |

### Local development
```bash
git clone <wherever you push this>
cd dispensary-report-card
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run the unit tests (no network required)
python test_report_card.py

# Run the CLI scanner against a live site
python report_card.py https://example-dispensary.com

# Run the web server locally
uvicorn app:app --reload --port 8000
# then open http://localhost:8000
```

### Required keys / external services
| Service | Required? | What for | Cost |
|---|---|---|---|
| Render account | Yes (for hosting) | Hosts the FastAPI service | $0/month free tier, $7/month always-on |
| Domain registrar | Optional | Custom domain (otherwise Render's default URL) | ~$12/year if you want one |
| Google Cloud + Places API key | Optional but recommended | Unlocks the 20% Local Search & GBP category beyond website-visible signals | $0/month effectively — $200/month free credit, ~$0.04/scan |

DEPLOY.md walks through obtaining each in order.

### What to know before you ship
- **The scanner is synchronous.** Each `/scan` request blocks until the scan completes (8–30s). Render's free tier has a per-request timeout that's adequate. Don't add this to a system that requires sub-second response.
- **Rate limit is in-memory** (`app._visits` dict). It resets on every cold start, which is fine for a soft launch but obviously not for production scale. For real abuse protection, add Cloudflare in front or move to Redis-backed rate limiting.
- **The signature detection is regex-based.** Platforms change their CDN URLs occasionally. When a signature breaks, it'll typically just stop detecting that platform — no crash. See "Extending the scanner" below.
- **No database, no scan history.** Every scan re-runs from scratch. If you need to add scan persistence (for a leaderboard, for example), the natural shape is: hash the URL + timestamp, store the JSON output in Postgres or SQLite, render shareable links from stored data. Roughly 100 lines of additional code.

### Extending the scanner
Adding detection for a new platform:
1. Add a signature pattern to `SIGS` dict in `report_card.py` (line ~55).
2. Add a check to the relevant `score_*()` function with point values.
3. Add it to the `detected` dict in `scan()` if you want it in the stack listing.
4. Add it to the `STACK_GROUPS` list (in the same file, near the rendering helpers) under the right group.
5. Add a unit test in `test_report_card.py`.
Tuning weights: edit the `.weight = 0.XX` lines in `scan()` (in `report_card.py`). The weights should sum to 1.0.

---

## Install (local dev)

Requires Python 3.10+.

```bash
pip install -r requirements.txt
```

## Run it

```bash
python report_card.py https://stokd.ca/
python report_card.py https://lakecitycannabis.ca/
python report_card.py https://yoursite.com --output my_report.html
python report_card.py https://yoursite.com --json > result.json
```

Each run prints a text summary to stdout and writes `report_<host>.html`.

## What it checks (scoring rubric)

| Category | Weight | Includes |
|---|---|---|
| SEO Fundamentals | 18% | Title, meta description, canonical, Open Graph, Twitter Card, Product schema, robots.txt, sitemap.xml, viewport |
| **E-commerce & Platform** | **17%** | Platform tier (S/A/B/C/F), clean URLs, product pages, HTTPS, cannabis taxonomy bonuses |
| Analytics & Tracking | 10% | GA4, GTM, Google Search Console, Meta Pixel, TikTok Pixel |
| Email Marketing | 17% | Newsletter form + ESP quality (Klaviyo > Omnisend > ActiveCampaign > Mailchimp) |
| Loyalty Program | 8% | AlpineIQ (active, not just bundled) > Springbig > Sticky Cards > Smile.io > branded |
| Retention & Reviews | 10% | AutomateWoo + Klaviyo, dedicated review platform (Yotpo/Stamped/Junip/Okendo), Google Reviews widget |
| Local Search & Google Business | 20% | Embedded widgets/Maps/multi-store on site; with API key: profile completeness, photos, rating, reviews, UTM on website link, multi-store deep links |

### E-commerce Platform Tier (max 25 pts of the 40 in the Ecom category)

| Tier | What it is | Points | Examples |
|---|---|---|---|
| **S** | True on-domain ecommerce | 23–25 | WooCommerce, Shopify, BigCommerce, Magento |
| **A** | Custom-built with SSR + sitemap | 22 | Next.js / Nuxt / Gatsby with product URLs indexable |
| **B** | Proxy/redirect cannabis platform | 14–16 | Blaze Ecom, Dispense (AIQ), Tymber, Greenline |
| **C** | Iframe embed or CSR SPA | 5–8 | Dutchie embed, Jane embed, Buddi embed, client-rendered React |
| **F** | No ecommerce | 0 | |

Modifiers: −5 for subdomain shop (`shop.example.com`), +3 for terpene taxonomy, +2 for minor cannabinoid taxonomy.

Letter grades: A ≥ 90, B ≥ 80, C ≥ 70, D ≥ 60, F otherwise.

## Google Business Profile (optional)

Set `GOOGLE_PLACES_API_KEY` env var to unlock the deeper GBP checks. Without the key the Local Search category falls back to website-visible signals only. With it, the scanner pulls live data from Google's Places API and scores:

- GBP found on Google Maps
- Profile completeness: phone, address, website link, hours
- Photos (≥10 for full credit)
- Rating ≥4.0 with ≥25 reviews
- Recent review activity (within ~90 days)
- Website link is HTTPS and matches scanned domain
- UTM parameters present on the GBP website link
- Multi-store deep link accuracy

DEPLOY.md Part 5 has the step-by-step API key setup.

## What it deliberately does NOT do

1. Verify abandoned-cart emails actually fire — only detects the capability is installed.
2. Verify post-purchase review requests fire — same problem.
3. Detect server-side analytics (events sent from backend via Measurement Protocol).
4. Owner reply rate on GBP reviews — Places API New doesn't reliably expose owner replies.
5. Map pack ranking — requires SerpApi or similar (~$50/mo), deferred.

## False positives we explicitly guard against

**Breadstack's bundled AlpineIQ integration.** Breadstack ships an AlpineIQ form whose CSS classes (`bs-alpineiq-*`) appear in the HTML even when AIQ isn't configured. We only credit a site with AIQ when actual `alpineiq.com` scripts are loading.

**Cova POS via Breadstack.** Cova shows up via Breadstack's `cova-*.js` integration files. Detected and listed in the stack, not scored — it's a POS, not a marketing stack item.

## Sample reports

`samples/report_stokd_ca.html`, `samples/report_lakecitycannabis_ca.html`, and `samples/report_plantlifecannabis_com.html` are pre-generated examples. Open them in any browser to see what the tool produces.

## Tests

```bash
python test_report_card.py
```

25 unit tests covering signature detection, scoring math, false-positive guards (especially AIQ bundled-vs-active), platform tier classification, subdomain penalty, terpene/cannabinoid bonuses, GBP scoring with and without API key, and end-to-end offline scans.

## Next steps (deferred)

When the tool gets traction:
- Move off free tier to kill cold starts ($7/mo).
- Add a leaderboard (Postgres on Render free tier, claim-your-listing flow, moderation).
- Real map pack ranking via SerpApi.
- Cache recent scans (don't re-run for the same URL within 24h).
- CSV export for industry benchmarking.

## License / ownership

Built for poof.ca. Use, modify, and deploy freely.

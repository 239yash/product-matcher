# Product Matcher

Paste an Amazon India product link → see whether the same product is **in stock / out of stock / not listed** on the right competitor platforms.

- Smartphones & Televisions → Flipkart + Croma
- Sneakers & Apparel → Flipkart + Myntra

For the matching logic in plain English, see **[EXPLANATION.md](EXPLANATION.md)**. For the one-page writeup (PDF), see **[Cross-platform-Product-Matcher.pdf](Cross-platform-Product-Matcher.pdf)**.

## How it works

Real scraping. No LLM. No API keys.

| Platform | Stack | Latency |
|---|---|---|
| Amazon India | `curl_cffi` (Chrome TLS impersonation) + HTML parse | ~1s |
| Flipkart | `curl_cffi` + HTML parse of search page + product page | ~1.5s |
| Myntra | `curl_cffi` + parse `window.__myx` hydration JSON | ~1.5s |
| Croma | `curl_cffi` to `api.croma.com/searchservices/v1/search` with their public APIM key | ~1s |

End-to-end: **~3.5 seconds per URL. Zero API cost.**

## Project structure

```
product-matcher/
├── app.py           Flask orchestrator — routes `/` and `/match`
├── scraper.py       Amazon + Flipkart + Myntra scrapers (curl_cffi)
├── croma.py         Croma via their internal API
├── index.html       Frontend — vanilla JS, served by Flask at /
├── requirements.txt flask, curl_cffi
├── README.md        this file
├── EXPLANATION.md   matching logic + production notes
└── Cross-platform-Product-Matcher.pdf  one-page writeup
```

Backend and frontend live in the same folder and are served by the same Flask process. One command, one port.

## Prerequisites

- Python 3.10 or later
- macOS, Linux, or Windows (tested on macOS)

## Run

```bash
git clone <repo-url> product-matcher
cd product-matcher

python3 -m venv .venv
source .venv/bin/activate        # on Windows: .venv\Scripts\activate
pip install -r requirements.txt

python app.py
```

Open http://127.0.0.1:5050 in a browser. Click one of the sample chips, or paste any Amazon India URL.

## Try these sample URLs

| Category | URL | Expected |
|---|---|---|
| Smartphone (in stock on Croma) | `https://www.amazon.in/dp/B0GL8GXNTS` | Samsung Galaxy S26 Ultra 512GB |
| Smartphone (sold out on Flipkart) | `https://www.amazon.in/dp/B0CS5Z3T4M` | Samsung Galaxy S24 Ultra 256GB |
| Sneaker (apparel path) | `https://www.amazon.in/dp/B0983NTYZ5` | Nike Court Vision Lo |

## How each platform was cracked

| Platform | Defence | How we got past |
|---|---|---|
| Amazon | TLS fingerprint check + bot reputation | `curl_cffi` sends a real Chrome TLS handshake — looks identical to a real browser at the network layer |
| Flipkart | None heavy — ships product cards server-rendered | Direct HTML parse |
| Myntra | SPA, but hydrates with full search JSON in `window.__myx` | Grab the script block, `json.JSONDecoder().raw_decode()` |
| Croma | Akamai Bot Manager on `www.croma.com` + APIM-protected `api.croma.com` | Read the APIM subscription key straight out of their public JS bundle; build the exact `?currentPage=0&query=<q>:relevance&fields=FULL&channel=WEB&channelCode=400001&spellOpt=DEFAULT` URL their SPA calls |

The Croma crack is the interesting one — their `api.croma.com/searchservices/v1/search` returns clean JSON with `products[]`, each item having `name`, `manufacturer`, `url`, `price.priceType`, and `stockFlag` (a list of store IDs where in stock — empty = OOS).

## Stock detection

- **Flipkart / Myntra** — keyword scan of the rendered page. "Add to Cart" / "Buy Now" wins over weak signals like "Notify Me" (which usually belongs to a variant on the same page). "Currently unavailable" always wins.
- **Croma** — direct boolean from the API: `stockFlag != [] and price.priceType == "BUY"` → in stock. Clean.

## Matching logic

For each candidate product on the target platform:
1. Brand must appear (case- and whitespace-insensitive, so `256 GB` == `256GB`).
2. **Any model token containing a digit must match exactly.** This prevents S24 Ultra from matching S26 Ultra when the brand + "ultra" tokens coincide.
3. At least half of the alpha-only model tokens must appear.
4. The category-specific "must-also-match" field (RAM + storage / screen size / colour) must appear.

## Troubleshooting

- **`ModuleNotFoundError`** — make sure the venv is active (`source .venv/bin/activate`).
- **Amazon returns `Could not read Amazon page`** — your IP may be rate-limited; wait a minute or try from a different network.
- **Croma returns `not_listed` unexpectedly** — Croma's APIM key is public but can rotate. If it does, pull the latest from `https://www.croma.com/static/js/main.*.chunk.js` (search for `OCP_APIM_SUBSCRIPTION_KEY`).

## Production notes

See [EXPLANATION.md](EXPLANATION.md) for the "how I'd scale this" section: offline catalog, browser extension as a data firehose, affiliate APIs where available, residential proxies for the gaps, caching.

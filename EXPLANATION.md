# How this product matcher works
*(Explained like you're five.)*

## The game

Imagine Amazon is one shop and Flipkart, Croma, Myntra are three other shops across the road. You hold up a toy and ask: **"Is this exact same toy sold in those other shops? And can I buy it today?"**

That's the game. The matcher plays it for you.

## Three simple steps

### 1. Look at the toy on Amazon

You give me a link to an Amazon page. I go to that page and I write down four things on a sticky note:

- **Who made it** (the brand, like *Samsung* or *Nike*)
- **What it's called** (the model, like *Galaxy S24 Ultra* or *Court Vision Lo*)
- **What kind of toy it is** (phone? TV? shoe? t-shirt?)
- **One more special detail that matters:**
  - Phones → RAM and storage (because "8GB 128GB" and "12GB 256GB" are *different* phones with the same name)
  - TVs → screen size
  - Shoes & clothes → colour

### 2. Pick which other shops to check

Different shops sell different things:

- **Phones and TVs** → look at Flipkart and Croma
- **Shoes and clothes** → look at Flipkart and Myntra

### 3. Visit each shop and check

For every shop I need to check:

1. Type the brand + model + special detail into that shop's search box.
2. Look at the first few results.
3. Ask: **"Is this the same toy?"** It's the same only if **all four things match** — brand, model, kind, and the special detail. (I ignore spaces and capitalisation so "256 GB" matches "256gb".)
4. If I find it, open the page and look for the buy button:
   - Button says **"Buy Now"** or **"Add to Cart"** → **In stock** ✅
   - Only **"Sold Out"** / **"Notify Me"** → **Out of stock** 🟠
5. If none of the results are the same toy → **Not listed** ⚪

Then I come back with the answer for each shop.

## How I actually read each shop's pages

Different shops defend themselves differently against robots like me. I use the lightest tool that works for each one:

| Shop | How I read it |
|---|---|
| **Amazon India** | Pretend to be a real Chrome browser (`curl_cffi` library). Works because my pretend browser has the same TLS fingerprint as real Chrome. |
| **Flipkart** | Same trick. Their search page already has clickable product links I can grab. |
| **Myntra** | Same trick, but Myntra buries all the product data in a JSON blob inside the page (`window.__myx`). I pull that out and parse it. |
| **Croma** | Hidden behind Akamai, a bodyguard service that catches robots. I went around the front door. See below. |

### How Croma was cracked

Croma's **website** blocks headless browsers via Akamai Bot Manager. But its SPA is a React app that calls a back-end API to get search results. I opened their JavaScript bundle (publicly served from `croma.com/static/js/`) and found:

1. The actual API URL: `https://api.croma.com/searchservices/v1/search`
2. The required header: `Ocp-Apim-Subscription-Key: 1131858141634e2abe2efb2b3a2a2a5d`  (hard-coded in the bundle — not a secret)
3. The exact query-string shape the SPA builds: `?currentPage=0&query=<q>:relevance&fields=FULL&channel=WEB&channelCode=<pincode>&spellOpt=DEFAULT`

Make that call directly with a real Chrome TLS fingerprint → clean JSON back. Each product has `name`, `manufacturer`, `url`, `price.priceType`, and `stockFlag` (a list of store codes where the SKU is in stock — empty = out of stock everywhere).

**This is how every price tracker works in practice:** find the undocumented back-end API, copy the keys out of the public JS, bypass the bot wall in front of the website entirely. No proxies, no headless browser, no LLM.

## Why it's not harder than that

The whole idea rests on one trick: **brand and model are already strong matching keys.** If Flipkart lists "Samsung Galaxy S24 Ultra 5G (256 GB Storage, 12 GB RAM)" and I'm looking for "Samsung Galaxy S24 Ultra 12GB RAM 256GB", those are the same phone. Humans see this instantly. My string-match-after-normalising-whitespace catches it too.

For typos, abbreviations, weird capitalisation, the pattern holds because retailer titles are usually copy-pasted from manufacturer catalogues.

## What I'm *not* doing — and why real companies do things differently

Big price-comparison companies (Google Shopping, MySmartPrice, BuyHatke, Xerve) **do not** look up products one at a time like this. It would be too slow and shops would block them. Instead:

1. **They have millions of users running their browser extension.** Every time a user opens an Amazon or Flipkart product page, the extension reads the product ID + price + stock from the page the user is already looking at and sends it to the company's server. Free, real-time, fully trusted data (because it's the user's own browser). This is BuyHatke and Xerve's main data pipeline.
2. **Nightly batches fill the gaps.** For products no user viewed recently, they fetch via affiliate APIs (Amazon PA-API requires Associates membership; Flipkart has one) or residential-proxy scraping.
3. **They match once, store forever.** A giant table says "Amazon ASIN X ≡ Flipkart PID Y ≡ Croma SKU Z". When any source reports a new price for X, the row updates. User queries are pure cache lookups — instant.
4. **Affiliate commissions pay for the infrastructure.** They get 2-8% on every sale referred, which pays for the proxies, servers, and team.

My version does it **live, every time** — which is what the assignment asks for. It's slower (4-30s per link depending on Croma), but needs almost no infrastructure.

## What would make this production-ready

1. **Build the catalog offline, not live.** Match once, cache forever. Serve users from the cache.
2. **Get affiliate API access** where it exists (Flipkart affiliate API, Amazon PA-API via Associates program).
3. **Ship a browser extension** as the primary data collection mechanism — the same trick BuyHatke/Xerve use. Free continuous data from every install.
4. **Residential proxies for the gaps** — Croma, Nykaa, Ajio. Bright Data or Oxylabs, ~$4-8/GB.
5. **Use an LLM only for the hard edge cases** — variants where strings don't match cleanly, or new categories the scraper doesn't know yet. Cheaper than human reviewers at scale.
6. **Store price history in ClickHouse / TimescaleDB** for the price-drop alerts feature every tracker eventually adds.

That's roughly the Google Shopping Graph model at a smaller scale.

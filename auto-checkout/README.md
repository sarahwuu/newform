# Auto Checkout Bot

A beginner-friendly bot that watches a product on a store and automatically
buys it the moment it's available: it logs in, polls the product page, adds
it to the cart, fills in your shipping info, and places the order.

It uses [Playwright](https://playwright.dev/python/), which drives a real
Chrome browser — so you can literally watch it click through checkout.

Out of the box it runs against **[saucedemo.com](https://www.saucedemo.com)**,
a free demo store made for practicing automation, so you can safely test the
whole flow end to end with fake products and no real money.

## Setup (one time)

```bash
cd auto-checkout
pip install -r requirements.txt
playwright install chromium
cp config.example.json config.json
```

## Run it

```bash
python checkout_bot.py
```

A Chrome window opens and you'll see it log in, find the product, add it to
the cart, and fill in checkout. By default `"dry_run": true` stops it right
before the final "place order" click. When you're happy with what it does,
set `"dry_run": false` in `config.json` to let it complete the order.

## Configuration (`config.json`)

| Key | What it does |
|---|---|
| `product_name` | The product to watch and buy |
| `shipping` | Your name and postal code for the checkout form |
| `poll_seconds` | How often to re-check if the product is available |
| `max_attempts` | How many checks before giving up |
| `dry_run` | `true` = stop before placing the order (safe default) |
| `headless` | `true` = run the browser invisibly in the background |

`config.json` is git-ignored so your personal info never gets committed —
only the example file is in the repo.

## Adapting it to a real store

All the site-specific logic lives in four small functions in
`checkout_bot.py` (`login`, `product_in_stock`, `add_to_cart`, `checkout`).
To point it at another site:

1. Open the store in Chrome, right-click each button/field in the checkout
   flow, and pick **Inspect** to find its `id` or `class`.
2. Replace the selectors (the strings like `"#login-button"`) in those four
   functions with the ones you found.
3. Test with `"dry_run": true` until every step works.

**Before automating a real store:** check its terms of service — most
retailers prohibit purchase bots and will cancel orders or ban accounts.
Automated ticket buying is illegal in the US (BOTS Act). Stick to sites you
own, demo sites, or stores that explicitly permit it.

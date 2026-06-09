# Auto Checkout — two tools

This folder has two related tools built on [Playwright](https://playwright.dev/python/)
(it drives a real Chrome browser, so you can watch everything happen):

1. **`watch_and_cart.py`** — the real one. A *hybrid* drop bot for Target,
   Walmart, etc. It watches a logged-in product page, auto-clicks "Add to
   cart" the instant the item is buyable, then sounds a loud alarm so **you**
   come and do the final checkout click. ← this is probably what you want.
2. **`checkout_bot.py`** — a *learning demo* that does a full hands-off
   checkout on [saucedemo.com](https://www.saucedemo.com), a free practice
   store. Great for understanding how browser automation works before
   pointing anything at a real site.

## Setup (one time, covers both)

```bash
cd auto-checkout
pip3 install -r requirements.txt
python3 -m playwright install chromium
```

---

## Tool 1 — Watch & Cart (Target / Walmart)

### Why hybrid?
On a hot drop, humans lose the race in two spots: **spotting** the moment
stock appears, and **carting** fast enough. The bot does both in under a
second. The part that's fragile and risky to automate — payment, 2FA, and
the final "Place Order" — stays with **you**. One human checkout click is
also what looks least like a bot to the store's detection.

### Set it up
```bash
cp watch_config.example.json watch_config.json
```
Open `watch_config.json` and paste your product's URL into `product_url`.

### Run it
```bash
python3 watch_and_cart.py
```
1. A Chrome window opens on the product page.
2. **Sign in by hand** the first time (and make sure your shipping + payment
   are saved on the account). Your login is remembered after that, so you
   only do this once. Press ENTER in the terminal when ready.
3. The bot watches the page, checking every few seconds.
4. The moment it's buyable, it clicks "Add to cart" and a **loud alarm**
   goes off. Walk over, solve any CAPTCHA if one appears, and **place the
   order yourself.**

### Settings (`watch_config.json`)
| Key | What it does |
|---|---|
| `product_url` | The exact product page to watch |
| `button_texts` | Button labels that mean "in stock" (defaults cover most stores) |
| `poll_seconds` | Base seconds between checks |
| `jitter_seconds` | Random extra wait, so it looks less robotic |
| `auto_add_to_cart` | `true` = bot carts it; `false` = bot only alarms, you cart |

### Honest limits
Target and Walmart actively fight bots. On a big drop you may hit a CAPTCHA
or "press and hold" challenge at the cart step. Since you're sitting right
there, that's fine — solve it and keep going. This tool is built to make
*you* faster, not to win while you're away from the keyboard. Automating
purchases also breaks most stores' terms of service, and they can cancel
orders or ban accounts — use your judgement, and never use this for ticket
sales (purchase bots for tickets are illegal in the US under the BOTS Act).

---

## Tool 2 — Full demo checkout (practice)

```bash
cp config.example.json config.json
python3 checkout_bot.py
```
Runs the whole flow on the demo store: log in → watch → add to cart → fill
shipping → place order. By default `"dry_run": true` stops right before the
final order click; set it to `false` to complete the (fake) purchase.

| Key | What it does |
|---|---|
| `product_name` | Product to watch and buy |
| `shipping` | Name + postal code for the checkout form |
| `poll_seconds` / `max_attempts` | How often / how many times to check |
| `dry_run` | `true` = stop before placing the order (safe default) |
| `headless` | `true` = run the browser invisibly |

---

Your `config.json`, `watch_config.json`, and saved `browser-profile/` login
are all git-ignored, so none of your personal info or accounts get committed.

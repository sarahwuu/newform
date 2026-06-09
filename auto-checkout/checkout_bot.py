"""
Auto Checkout Bot
=================
Watches a product on a store, and as soon as it's available it adds it to
the cart, fills in your shipping info, and completes checkout.

This version runs against https://www.saucedemo.com — a free demo store
built for practicing browser automation. To use it on another site you
only need to change the selectors in the STORE section below (and make
sure the site's terms of service allow automation).

How to run:
    1. pip install -r requirements.txt
    2. playwright install chromium
    3. Edit config.json with the product you want and your info
    4. python checkout_bot.py

Safety: config.json has "dry_run": true by default, which stops right
before the final "place order" click so you can verify everything first.
"""

import json
import sys
import time

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
def load_config():
    try:
        with open("config.json") as f:
            return json.load(f)
    except FileNotFoundError:
        print("config.json not found. Copy config.example.json to config.json first.")
        sys.exit(1)


# ──────────────────────────────────────────────
# STORE: every step of the saucedemo checkout.
# To adapt to another store, rewrite these
# functions with that site's URLs and selectors.
# (Right-click an element in Chrome → Inspect to
# find its id/class.)
# ──────────────────────────────────────────────
def login(page, config):
    print("→ Logging in…")
    page.goto(config["store_url"])
    page.fill("#user-name", config["login"]["username"])
    page.fill("#password", config["login"]["password"])
    page.click("#login-button")
    # Wait until the product list is visible so we know login worked
    page.wait_for_selector(".inventory_list", timeout=10_000)
    print("  Logged in.")


def product_in_stock(page, product_name):
    """A product is buyable if its card shows an 'Add to cart' button."""
    card = page.locator(".inventory_item").filter(has_text=product_name)
    if card.count() == 0:
        return False
    return card.locator("button", has_text="Add to cart").count() > 0


def add_to_cart(page, product_name):
    print(f"→ Adding '{product_name}' to cart…")
    card = page.locator(".inventory_item").filter(has_text=product_name)
    card.locator("button", has_text="Add to cart").click()
    print("  Added.")


def checkout(page, config):
    print("→ Checking out…")
    page.click(".shopping_cart_link")
    page.click("#checkout")

    shipping = config["shipping"]
    page.fill("#first-name", shipping["first_name"])
    page.fill("#last-name", shipping["last_name"])
    page.fill("#postal-code", shipping["postal_code"])
    page.click("#continue")

    # We're now on the order review page (items + total)
    total = page.locator(".summary_total_label").inner_text()
    print(f"  Order review reached. {total}")

    if config.get("dry_run", True):
        print("  DRY RUN — stopping before placing the order.")
        print("  Set \"dry_run\": false in config.json to complete checkout.")
        return False

    page.click("#finish")
    page.wait_for_selector(".complete-header", timeout=10_000)
    confirmation = page.locator(".complete-header").inner_text()
    print(f"  ✓ Order placed: {confirmation}")
    return True


# ──────────────────────────────────────────────
# Main loop: poll until in stock, then buy
# ──────────────────────────────────────────────
def main():
    config = load_config()
    product = config["product_name"]
    poll_seconds = config.get("poll_seconds", 5)
    max_attempts = config.get("max_attempts", 60)

    with sync_playwright() as p:
        # headless=False opens a visible browser window so you can watch.
        # Set "headless": true in config.json to run invisibly.
        browser = p.chromium.launch(headless=config.get("headless", False))
        page = browser.new_page()

        try:
            login(page, config)

            print(f"→ Watching '{product}' (checking every {poll_seconds}s)…")
            for attempt in range(1, max_attempts + 1):
                if product_in_stock(page, product):
                    print(f"  In stock on attempt {attempt}!")
                    add_to_cart(page, product)
                    checkout(page, config)
                    break
                print(f"  Attempt {attempt}/{max_attempts}: not available, retrying…")
                time.sleep(poll_seconds)
                page.reload()
            else:
                print("Gave up: product never became available.")

        except PlaywrightTimeout as e:
            print(f"Timed out waiting for the page — the site may have changed. {e}")
        finally:
            browser.close()


if __name__ == "__main__":
    main()

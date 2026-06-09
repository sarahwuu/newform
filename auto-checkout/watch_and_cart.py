"""
Watch & Cart  —  hybrid drop bot
================================
Sits in a logged-in browser, watches one product page, and the moment the
item is buyable it clicks "Add to cart" for you and sets off a loud alarm.
You walk over and do the final "Place Order" click yourself.

Why this split?
  • The bot handles the part where milliseconds matter (spotting the drop
    + carting), which is where humans lose the race.
  • YOU handle payment / 2FA / placing the order — the fragile, risky part,
    and the part that looks least like a bot to the store's detection.

Works on Target, Walmart, or most stores — you just paste the product URL
into config.json. It logs in by letting YOU log in by hand once, then
remembers you (the browser profile is saved in browser-profile/).

⚠️  Reality check: big retailers actively try to block bots. On a hot drop
    you may get a CAPTCHA or "press and hold" challenge at the cart step.
    Because you're sitting right there, that's fine — solve it and keep
    going. This tool is built to assist you, not to beat their defenses
    while you're away. Automating purchases also breaks most stores' terms
    of service; use your judgement.

Run it:
    python3 watch_and_cart.py
"""

import json
import random
import subprocess
import sys
import threading
import time

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
def load_config():
    try:
        with open("watch_config.json") as f:
            return json.load(f)
    except FileNotFoundError:
        print("watch_config.json not found.")
        print("Copy watch_config.example.json to watch_config.json and edit it.")
        sys.exit(1)


# ──────────────────────────────────────────────
# The alarm — loud and repeating until you stop it
# ──────────────────────────────────────────────
class Alarm:
    """Plays a sound on a loop in the background until .stop() is called."""

    def __init__(self):
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                # macOS: play a built-in system sound + speak out loud.
                subprocess.run(
                    ["afplay", "/System/Library/Sounds/Glass.aiff"],
                    timeout=5,
                )
                subprocess.run(["say", "Item is in your cart. Go check out."], timeout=5)
            except Exception:
                # Fallback for any system: terminal bell.
                print("\a", end="", flush=True)
                time.sleep(1)

    def stop(self):
        self._stop.set()


# ──────────────────────────────────────────────
# Is the product buyable right now?
# ──────────────────────────────────────────────
def find_buy_button(page, button_texts):
    """
    Returns a clickable buy button if the item is in stock, else None.

    We look for a VISIBLE, ENABLED button whose text matches one of the
    phrases in button_texts (e.g. "Add to cart"). When an item is sold out,
    that button is gone or disabled, so this returns None.
    """
    for text in button_texts:
        buttons = page.get_by_role("button", name=text, exact=False)
        count = buttons.count()
        for i in range(count):
            btn = buttons.nth(i)
            try:
                if btn.is_visible() and btn.is_enabled():
                    return btn
            except Exception:
                continue
    return None


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def main():
    config = load_config()
    url = config["product_url"]
    button_texts = config.get("button_texts", ["Add to cart", "Buy now", "Preorder"])
    poll = config.get("poll_seconds", 3)
    jitter = config.get("jitter_seconds", 2)
    auto_cart = config.get("auto_add_to_cart", True)

    with sync_playwright() as p:
        # A PERSISTENT browser: your login is saved in ./browser-profile so
        # you only have to sign in by hand once. Visible window (headless
        # off) so you can watch and take over instantly.
        browser = p.chromium.launch_persistent_context(
            user_data_dir="browser-profile",
            headless=False,
            viewport={"width": 1280, "height": 900},
        )
        page = browser.pages[0] if browser.pages else browser.new_page()

        try:
            print(f"→ Opening {url}")
            page.goto(url, wait_until="domcontentloaded")

            # ── One-time manual login ──
            print()
            print("=" * 60)
            print("STEP 1 — Log in (only needed the first time)")
            print("  In the browser window that just opened, sign in to your")
            print("  account and make sure your shipping + payment are saved.")
            print("  Leave the page ON the product you want.")
            print()
            input("  When you're logged in and ready, press ENTER here… ")
            print("=" * 60)

            # ── Watch loop ──
            print(f"→ Watching for stock (checking ~every {poll}s). Ctrl+C to stop.")
            attempt = 0
            while True:
                attempt += 1
                btn = find_buy_button(page, button_texts)

                if btn:
                    print(f"\n🟢 IN STOCK (check #{attempt})!")
                    if auto_cart:
                        try:
                            btn.click()
                            print("🛒 Clicked the buy button — item should be in your cart.")
                        except Exception as e:
                            print(f"⚠️  Couldn't click automatically ({e}).")
                            print("    Take over in the browser — it's in stock NOW.")
                    else:
                        print("    (auto-cart off) — go add it yourself, it's live.")
                    break

                wait = poll + random.uniform(0, jitter)
                print(f"  check #{attempt}: not available — retry in {wait:.1f}s", end="\r")
                time.sleep(wait)
                try:
                    page.reload(wait_until="domcontentloaded")
                except PlaywrightTimeout:
                    print("\n  (slow reload — retrying)")

            # ── Alarm + hand off to you ──
            alarm = Alarm()
            alarm.start()
            print()
            print("█" * 60)
            print("  GO TO THE BROWSER AND COMPLETE CHECKOUT NOW")
            print("  (Solve any CAPTCHA / 'press and hold' if it appears.)")
            print("█" * 60)
            input("\nPress ENTER here to silence the alarm… ")
            alarm.stop()

            print("\nLeaving the browser open so you can finish.")
            input("Press ENTER to close the browser when you're done. ")

        except KeyboardInterrupt:
            print("\nStopped.")
        finally:
            browser.close()


if __name__ == "__main__":
    main()

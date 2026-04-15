"""Reproduce/verify scroll-position preservation when opening+closing detail modal.

Usage:
  python scripts/pw_scroll_repro.py <jwt> [viewport desktop|mobile]
"""
import sys
from playwright.sync_api import sync_playwright

jwt = sys.argv[1]
mode = sys.argv[2] if len(sys.argv) > 2 else 'desktop'

viewport = {'width': 1440, 'height': 900} if mode == 'desktop' else {'width': 390, 'height': 844}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport=viewport)
    ctx.add_cookies([{
        'name': 'session', 'value': jwt,
        'domain': 'localhost', 'path': '/', 'httpOnly': True, 'secure': False, 'sameSite': 'Lax',
    }])
    page = ctx.new_page()
    page.goto('http://localhost:4200/', wait_until='networkidle')
    # Dismiss first-visit category modal if present — set category
    page.evaluate("() => localStorage.setItem('rcn_category', 'all')")
    page.reload(wait_until='networkidle')
    page.wait_for_selector('a[href^="/listings/"]', timeout=10000)

    # Scroll down to load more pages
    for _ in range(5):
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(400)
    page.wait_for_timeout(800)

    scroll_before = page.evaluate('() => window.scrollY')
    cards = page.locator('a[href^="/listings/"]')
    count = cards.count()
    print(f'[{mode}] scrollY before click: {scroll_before}  (cards: {count})')

    # Pick a card near the current viewport
    target = None
    for i in range(count):
        box = cards.nth(i).bounding_box()
        if box and 0 < box['y'] < viewport['height']:
            target = cards.nth(i)
            href = cards.nth(i).get_attribute('href')
            print(f'  clicking card {i} at y={box["y"]:.0f}  href={href}')
            break
    if target is None:
        target = cards.nth(count - 1)
        print('  no in-viewport card found, using last')

    target.click()
    page.wait_for_selector('[role="dialog"][aria-modal="true"]', timeout=5000)
    page.wait_for_timeout(500)

    # Close modal (Escape)
    page.keyboard.press('Escape')
    page.wait_for_timeout(800)

    scroll_after = page.evaluate('() => window.scrollY')
    print(f'[{mode}] scrollY after close: {scroll_after}')
    delta = abs(scroll_before - scroll_after)
    status = 'OK' if delta < 20 else 'BROKEN'
    print(f'[{mode}] delta: {delta}  -> {status}')

    # Also test: nested navigation A -> B -> close
    print(f'[{mode}] -- nested test --')
    page.goto('http://localhost:4200/', wait_until='networkidle')
    for _ in range(3):
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(400)
    page.wait_for_timeout(500)
    scroll_before2 = page.evaluate('() => window.scrollY')
    print(f'[{mode}] nested scrollY before: {scroll_before2}')
    cards = page.locator('a[href^="/listings/"]')
    cards.first.click()
    page.wait_for_selector('[role="dialog"][aria-modal="true"]', timeout=5000)
    page.wait_for_timeout(800)
    # Click close (X) button if present
    close_btn = page.locator('[role="dialog"] button[aria-label*="lie" i], [role="dialog"] button:has-text("×")').first
    try:
        close_btn.click(timeout=1500)
    except Exception:
        page.keyboard.press('Escape')
    page.wait_for_timeout(800)
    scroll_after2 = page.evaluate('() => window.scrollY')
    print(f'[{mode}] nested scrollY after: {scroll_after2}  delta={abs(scroll_before2-scroll_after2)}')

    browser.close()

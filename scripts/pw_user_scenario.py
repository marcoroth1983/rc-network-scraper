"""Simulate realistic user: scroll deep, click card in middle, wait in detail, close."""
import sys
from playwright.sync_api import sync_playwright

jwt = sys.argv[1]
mode = sys.argv[2] if len(sys.argv) > 2 else 'desktop'
viewport = {'width': 1440, 'height': 900} if mode == 'desktop' else {'width': 390, 'height': 844}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport=viewport)
    ctx.add_cookies([{'name':'session','value':jwt,'domain':'localhost','path':'/','httpOnly':True,'secure':False,'sameSite':'Lax'}])
    page = ctx.new_page()
    page.goto('http://localhost:4200/', wait_until='networkidle')
    page.evaluate("() => localStorage.setItem('rcn_category','all')")
    page.reload(wait_until='networkidle')
    page.wait_for_selector('a[href^="/listings/"]')

    for _ in range(8):
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(350)
    page.wait_for_timeout(800)

    y0 = page.evaluate('() => window.scrollY')
    print(f'[{mode}] initial scroll: {y0}')

    # Pick a card near viewport middle
    cards = page.locator('a[href^="/listings/"]')
    chosen = None
    for i in range(cards.count()):
        box = cards.nth(i).bounding_box()
        if box and 200 < box['y'] < viewport['height'] - 300:
            chosen = cards.nth(i); cy = box['y']; break
    assert chosen, 'no card'
    print(f'  clicking at y={cy:.0f}')
    chosen.click()

    page.wait_for_selector('[role="dialog"][aria-modal="true"]')
    page.wait_for_timeout(1500)

    # Scroll INSIDE modal (simulating reading)
    page.mouse.wheel(0, 600)
    page.wait_for_timeout(500)
    print(f'  body.top while modal open: {page.evaluate("() => document.body.style.top")}')

    # Close: try X button first
    closed = False
    for sel in ['[role="dialog"] button[aria-label="Schließen"]',
                '[role="dialog"] button[aria-label*="schließ" i]',
                '[role="dialog"] button[aria-label*="close" i]']:
        try:
            btn = page.locator(sel).first
            btn.click(timeout=1200)
            closed = True
            print(f'  closed via {sel}'); break
        except Exception:
            continue
    if not closed:
        page.keyboard.press('Escape')
        print('  closed via Escape')

    page.wait_for_timeout(1000)
    y1 = page.evaluate('() => window.scrollY')
    delta = abs(y0 - y1)
    print(f'[{mode}] after close: {y1}  delta={delta}  -> {"OK" if delta < 20 else "BROKEN"}')

    # --- Nested navigation test (click similar listing inside modal) ---
    print(f'\n[{mode}] --- NESTED TEST ---')
    # Find another card, click it
    cards = page.locator('a[href^="/listings/"]')
    for i in range(cards.count()):
        box = cards.nth(i).bounding_box()
        if box and 200 < box['y'] < viewport['height'] - 300:
            cards.nth(i).click(); break
    page.wait_for_selector('[role="dialog"][aria-modal="true"]')
    page.wait_for_timeout(1500)

    # Inside the modal, scroll to find author's other listings or a link within modal
    page.evaluate('() => document.querySelector("[role=dialog]").scrollTo({top: document.querySelector("[role=dialog]").scrollHeight, behavior: "instant"})')
    page.wait_for_timeout(500)
    inner_links = page.locator('[role="dialog"] a[href^="/listings/"]')
    print(f'  inner links in modal: {inner_links.count()}')
    if inner_links.count() > 0:
        inner_links.first.click()
        page.wait_for_timeout(1500)
        print('  clicked nested card')
        # Now close modal
        page.keyboard.press('Escape')
        page.wait_for_timeout(1000)
        y2 = page.evaluate('() => window.scrollY')
        print(f'[{mode}] nested close scrollY: {y2}  delta_from_initial={abs(y0-y2)}')

    browser.close()

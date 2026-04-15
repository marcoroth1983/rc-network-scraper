"""Trace scrollY and body styles throughout the modal open/close cycle."""
import sys
from playwright.sync_api import sync_playwright

jwt = sys.argv[1]
mode = sys.argv[2] if len(sys.argv) > 2 else 'desktop'
viewport = {'width': 1440, 'height': 900} if mode == 'desktop' else {'width': 390, 'height': 844}

TRACE = """() => ({
  scrollY: window.scrollY,
  pageYOffset: window.pageYOffset,
  docHeight: document.documentElement.scrollHeight,
  bodyHeight: document.body.scrollHeight,
  bodyTop: document.body.style.top,
  bodyPos: document.body.style.position,
  bodyOverflow: document.body.style.overflow,
  url: location.pathname,
})"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport=viewport)
    ctx.add_cookies([{
        'name': 'session', 'value': jwt,
        'domain': 'localhost', 'path': '/', 'httpOnly': True, 'secure': False, 'sameSite': 'Lax',
    }])
    page = ctx.new_page()
    page.on('console', lambda m: print(f'  console[{m.type}]: {m.text}'))
    page.goto('http://localhost:4200/', wait_until='networkidle')
    page.evaluate("() => localStorage.setItem('rcn_category', 'all')")
    page.reload(wait_until='networkidle')
    page.wait_for_selector('a[href^="/listings/"]', timeout=10000)

    for _ in range(5):
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(400)
    page.wait_for_timeout(800)

    print('BEFORE click:', page.evaluate(TRACE))

    cards = page.locator('a[href^="/listings/"]')
    count = cards.count()
    for i in range(count):
        box = cards.nth(i).bounding_box()
        if box and 0 < box['y'] < 80:
            print(f'  clicking card {i} at y={box["y"]:.0f}')
            cards.nth(i).click()
            break

    page.wait_for_selector('[role="dialog"][aria-modal="true"]', timeout=5000)
    page.wait_for_timeout(300)
    print('MODAL OPEN:', page.evaluate(TRACE))

    page.wait_for_timeout(500)
    print('MODAL OPEN (after 500ms):', page.evaluate(TRACE))

    page.keyboard.press('Escape')
    page.wait_for_timeout(100)
    print('AFTER close (100ms):', page.evaluate(TRACE))
    page.wait_for_timeout(800)
    print('AFTER close (900ms):', page.evaluate(TRACE))

    browser.close()

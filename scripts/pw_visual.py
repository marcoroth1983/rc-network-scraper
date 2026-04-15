"""Visual: does removing body-lock cause underlying scroll/flicker issues?"""
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
        page.mouse.wheel(0, 2500); page.wait_for_timeout(300)
    page.wait_for_timeout(1000)

    y0 = page.evaluate('() => window.scrollY')
    page.screenshot(path=f'/tmp/before_{mode}.png', full_page=False)

    cards = page.locator('a[href^="/listings/"]')
    for i in range(cards.count()):
        box = cards.nth(i).bounding_box()
        if box and 300 < box['y'] < viewport['height']-300:
            cards.nth(i).click(); break
    page.wait_for_selector('[role="dialog"][aria-modal="true"]')
    page.wait_for_timeout(1500)
    page.screenshot(path=f'/tmp/modal_{mode}.png', full_page=False)

    # Scroll inside modal
    page.mouse.wheel(0, 800)
    page.wait_for_timeout(500)

    # Close
    page.keyboard.press('Escape')
    page.wait_for_timeout(1200)
    y1 = page.evaluate('() => window.scrollY')
    page.screenshot(path=f'/tmp/after_{mode}.png', full_page=False)
    print(f'[{mode}] before={y0} after={y1} delta={abs(y0-y1)}')
    browser.close()

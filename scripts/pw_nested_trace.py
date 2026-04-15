"""Trace nested navigation A->B->close scroll restore."""
import sys
from playwright.sync_api import sync_playwright

jwt = sys.argv[1]
mode = sys.argv[2] if len(sys.argv) > 2 else 'desktop'
viewport = {'width': 1440, 'height': 900} if mode == 'desktop' else {'width': 390, 'height': 844}

TRACE = """() => ({
  y: window.scrollY, top: document.body.style.top, pos: document.body.style.position,
  url: location.pathname, modals: document.querySelectorAll('[role=dialog][aria-modal=true]').length,
})"""

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
    page.wait_for_timeout(800)
    print('0 BEFORE click:', page.evaluate(TRACE))

    # Click first card in middle
    cards = page.locator('a[href^="/listings/"]')
    for i in range(cards.count()):
        box = cards.nth(i).bounding_box()
        if box and 300 < box['y'] < viewport['height']-300:
            cards.nth(i).click(); break
    page.wait_for_selector('[role="dialog"][aria-modal="true"]')
    page.wait_for_timeout(1500)
    print('1 MODAL A open:', page.evaluate(TRACE))

    # Click nested card inside modal
    modal_cards = page.locator('[role="dialog"] a[href^="/listings/"]')
    print(f'  nested link count: {modal_cards.count()}')
    if modal_cards.count() == 0:
        # Force nested by pressing a modal link via JS find
        print('  no nested card found; scrolling modal to find one')
        page.evaluate('() => { const d=document.querySelector("[role=dialog]"); d.scrollTo({top: d.scrollHeight}); }')
        page.wait_for_timeout(800)
        modal_cards = page.locator('[role="dialog"] a[href^="/listings/"]')
        print(f'  after scroll: {modal_cards.count()}')
    if modal_cards.count() > 0:
        modal_cards.first.click()
        page.wait_for_timeout(1500)
        print('2 MODAL B open:', page.evaluate(TRACE))

        page.keyboard.press('Escape')
        page.wait_for_timeout(500)
        print('3 After 1st Escape:', page.evaluate(TRACE))

        page.keyboard.press('Escape')
        page.wait_for_timeout(500)
        print('4 After 2nd Escape:', page.evaluate(TRACE))
    else:
        print('  SKIP nested — no inner listing link available')
        page.keyboard.press('Escape')
        page.wait_for_timeout(500)
        print('3 After Escape (single):', page.evaluate(TRACE))

    browser.close()

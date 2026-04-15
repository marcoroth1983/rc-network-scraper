"""Check for layout shift from scrollbar disappearance when modal opens."""
import sys
from playwright.sync_api import sync_playwright

jwt = sys.argv[1]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
    ctx.add_cookies([{'name':'session','value':jwt,'domain':'localhost','path':'/','httpOnly':True,'secure':False,'sameSite':'Lax'}])
    page = ctx.new_page()
    page.goto('http://localhost:4200/', wait_until='networkidle')
    page.evaluate("() => localStorage.setItem('rcn_category','all')")
    page.reload(wait_until='networkidle')
    page.wait_for_selector('a[href^="/listings/"]')
    for _ in range(5):
        page.mouse.wheel(0, 2500); page.wait_for_timeout(300)
    page.wait_for_timeout(800)

    # Measure content width before modal
    before = page.evaluate("""() => {
      const main = document.querySelector('main');
      const header = document.querySelector('header');
      return {
        mainW: main.getBoundingClientRect().width,
        headerW: header ? header.getBoundingClientRect().width : 0,
        bodyW: document.body.getBoundingClientRect().width,
        innerW: window.innerWidth,
        scrollbarW: window.innerWidth - document.documentElement.clientWidth,
      };
    }""")
    print('BEFORE:', before)

    cards = page.locator('a[href^="/listings/"]')
    for i in range(cards.count()):
        box = cards.nth(i).bounding_box()
        if box and 300 < box['y'] < 600:
            cards.nth(i).click(); break
    page.wait_for_selector('[role="dialog"][aria-modal="true"]')
    page.wait_for_timeout(500)
    during = page.evaluate("""() => {
      const main = document.querySelector('main');
      const header = document.querySelector('header');
      return {
        mainW: main.getBoundingClientRect().width,
        headerW: header ? header.getBoundingClientRect().width : 0,
        bodyW: document.body.getBoundingClientRect().width,
        innerW: window.innerWidth,
        scrollbarW: window.innerWidth - document.documentElement.clientWidth,
      };
    }""")
    print('DURING:', during)
    shift = before['scrollbarW'] - during['scrollbarW']
    print(f'layout shift (scrollbar gap): {shift}px')
    browser.close()

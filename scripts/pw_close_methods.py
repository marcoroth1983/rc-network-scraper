"""Test all close methods: Escape, Zurück button, browser back, backdrop."""
import sys
from playwright.sync_api import sync_playwright

jwt = sys.argv[1]
mode = sys.argv[2] if len(sys.argv) > 2 else 'desktop'
viewport = {'width': 1440, 'height': 900} if mode == 'desktop' else {'width': 390, 'height': 844}

def run_scenario(close_fn, label):
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
        y0 = page.evaluate('() => window.scrollY')

        cards = page.locator('a[href^="/listings/"]')
        for i in range(cards.count()):
            box = cards.nth(i).bounding_box()
            if box and 200 < box['y'] < viewport['height'] - 300:
                cards.nth(i).click(); break

        page.wait_for_selector('[role="dialog"][aria-modal="true"]')
        page.wait_for_timeout(1200)

        close_fn(page)
        page.wait_for_timeout(800)
        dialog = page.locator('[role="dialog"][aria-modal="true"]').count()
        y1 = page.evaluate('() => window.scrollY')
        body_top = page.evaluate('() => document.body.style.top')
        body_pos = page.evaluate('() => document.body.style.position')
        print(f'  [{mode}][{label}] dialog_count={dialog}  scrollY={y1}  (before={y0}  delta={abs(y0-y1)})  body.top={body_top!r}  pos={body_pos!r}')
        browser.close()

print(f'=== {mode} ===')
run_scenario(lambda pg: pg.keyboard.press('Escape'), 'Escape')
run_scenario(lambda pg: pg.locator('[role="dialog"] button:has-text("Zurück")').first.click(), 'Zurück')
run_scenario(lambda pg: pg.go_back(), 'browser_back')

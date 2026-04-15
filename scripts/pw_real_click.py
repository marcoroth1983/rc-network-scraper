"""Click via JS (no Playwright scrollIntoView) to simulate real user click."""
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
    page.wait_for_timeout(800)

    y0 = page.evaluate('() => window.scrollY')
    print(f'[{mode}] before: {y0}')

    # Real-user click via JS — no Playwright scrollIntoView
    clicked_y = page.evaluate("""() => {
      const links = document.querySelectorAll('a[href^="/listings/"]');
      for (const a of links) {
        const r = a.getBoundingClientRect();
        if (r.top > 30 && r.top < 300) {
          a.click();
          return r.top;
        }
      }
      return null;
    }""")
    print(f'  clicked card at y={clicked_y}')

    page.wait_for_selector('[role="dialog"][aria-modal="true"]:visible')
    page.wait_for_timeout(1200)

    y_during = page.evaluate('() => window.scrollY')
    html_ov = page.evaluate('() => document.documentElement.style.overflow')
    body_pos = page.evaluate('() => document.body.style.position')
    print(f'  modal open: scrollY={y_during} html.overflow={html_ov!r} body.pos={body_pos!r}')

    page.keyboard.press('Escape')
    page.wait_for_timeout(800)
    y1 = page.evaluate('() => window.scrollY')
    print(f'[{mode}] after close: {y1}  delta={abs(y0-y1)}  -> {"OK" if abs(y0-y1) < 20 else "BROKEN"}')

    # Also test: click at very top of viewport (simulating user clicking a barely-visible card)
    print(f'\n[{mode}] -- click-at-top test --')
    y0b = page.evaluate('() => window.scrollY')
    clicked_y = page.evaluate("""() => {
      const links = document.querySelectorAll('a[href^="/listings/"]');
      for (const a of links) {
        const r = a.getBoundingClientRect();
        if (r.top > 0 && r.top < 30) {
          a.click();
          return r.top;
        }
      }
      return null;
    }""")
    print(f'  clicked at y={clicked_y}, before={y0b}')
    page.wait_for_selector('[role="dialog"][aria-modal="true"]:visible')
    page.wait_for_timeout(1200)
    page.keyboard.press('Escape')
    page.wait_for_timeout(800)
    y1b = page.evaluate('() => window.scrollY')
    print(f'[{mode}] after close: {y1b}  delta={abs(y0b-y1b)}  -> {"OK" if abs(y0b-y1b) < 20 else "BROKEN"}')

    browser.close()

"""Final verification on desktop with JS click."""
import sys
from playwright.sync_api import sync_playwright

jwt = sys.argv[1]
viewport = {'width': 1440, 'height': 900}

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
    print(f'before: {y0}')

    positions = page.evaluate("""() => {
      const links = document.querySelectorAll('a[href^="/listings/"]');
      const visible = [];
      for (const a of links) {
        const r = a.getBoundingClientRect();
        if (r.top > 0 && r.top < 900 && r.width > 0) visible.push({y: r.top, href: a.getAttribute('href')});
      }
      return visible;
    }""")
    print(f'visible links: {len(positions)}, y positions: {[p["y"] for p in positions[:10]]}')

    # Click a card in viewport (any visible one)
    clicked = page.evaluate("""() => {
      const links = document.querySelectorAll('a[href^="/listings/"]');
      for (const a of links) {
        const r = a.getBoundingClientRect();
        if (r.top > 200 && r.top < 600 && r.width > 50) {
          a.click();
          return r.top;
        }
      }
      return null;
    }""")
    print(f'clicked at y={clicked}')
    page.wait_for_function('() => document.querySelector("[role=dialog][aria-modal=true]")?.offsetWidth > 500', timeout=5000)
    page.wait_for_timeout(1200)

    y_during = page.evaluate('() => window.scrollY')
    html_ov = page.evaluate('() => document.documentElement.style.overflow')
    print(f'modal open: scrollY={y_during} html.overflow={html_ov!r}')

    # Scroll inside modal to see it works
    page.mouse.wheel(0, 600)
    page.wait_for_timeout(500)
    y_during2 = page.evaluate('() => window.scrollY')
    modal_scroll = page.evaluate('() => document.querySelector("[role=dialog][aria-modal=true]").scrollTop')
    print(f'after wheel: window.scrollY={y_during2} modal.scrollTop={modal_scroll}')

    page.keyboard.press('Escape')
    page.wait_for_timeout(1000)
    y1 = page.evaluate('() => window.scrollY')
    print(f'after close: {y1}  delta={abs(y0-y1)}  -> {"OK" if abs(y0-y1) < 20 else "BROKEN"}')

    browser.close()

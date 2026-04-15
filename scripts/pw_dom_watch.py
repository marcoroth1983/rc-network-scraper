"""Watch scrollHeight / DOM mutations during click at top-of-viewport."""
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
    for _ in range(5):
        page.mouse.wheel(0, 2000); page.wait_for_timeout(400)
    page.wait_for_timeout(800)

    page.evaluate("""() => {
      window.__log = [];
      const snap = (tag) => window.__log.push({
        tag, t: performance.now(),
        y: window.scrollY, dh: document.documentElement.scrollHeight,
        top: document.body.style.top, pos: document.body.style.position,
        url: location.pathname,
      });
      window.addEventListener('scroll', () => snap('scroll'), { capture: true, passive: true });
      // Observe child list changes on main
      const main = document.querySelector('main');
      new MutationObserver(muts => snap('mutate ' + muts.length)).observe(main, { childList: true, subtree: true });
      // Override history.pushState
      const origPush = history.pushState;
      history.pushState = function(...a) { snap('pushState ' + a[2]); return origPush.apply(this, a); };
      const origReplace = history.replaceState;
      history.replaceState = function(...a) { snap('replaceState ' + a[2]); return origReplace.apply(this, a); };
      snap('start');
    }""")

    cards = page.locator('a[href^="/listings/"]')
    for i in range(cards.count()):
        box = cards.nth(i).bounding_box()
        if box and 0 < box['y'] < 80:
            print(f'clicking card {i} at y={box["y"]:.0f}')
            cards.nth(i).click()
            break

    page.wait_for_selector('[role="dialog"][aria-modal="true"]')
    page.wait_for_timeout(500)
    log = page.evaluate('() => window.__log')
    for e in log:
        print(f'  {e["t"]:8.1f} {e["tag"]:30s}  y={e["y"]:6}  dh={e["dh"]:6}  top={e["top"]:12} url={e["url"]}')
    browser.close()

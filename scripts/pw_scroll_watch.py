"""Watch scroll events during click -> modal mount."""
import sys
from playwright.sync_api import sync_playwright

jwt = sys.argv[1]
viewport = {'width': 1440, 'height': 900}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport=viewport)
    ctx.add_cookies([{
        'name': 'session', 'value': jwt,
        'domain': 'localhost', 'path': '/', 'httpOnly': True, 'secure': False, 'sameSite': 'Lax',
    }])
    page = ctx.new_page()
    page.on('console', lambda m: print(f'  [{m.type}] {m.text}'))
    page.goto('http://localhost:4200/', wait_until='networkidle')
    page.evaluate("() => localStorage.setItem('rcn_category', 'all')")
    page.reload(wait_until='networkidle')
    page.wait_for_selector('a[href^="/listings/"]', timeout=10000)

    for _ in range(5):
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(400)
    page.wait_for_timeout(800)

    # Install scroll watcher
    page.evaluate("""() => {
      window.__scrollLog = [];
      const onScroll = () => {
        window.__scrollLog.push({
          y: window.scrollY, t: performance.now(),
          top: document.body.style.top, pos: document.body.style.position,
          stack: new Error().stack?.split('\\n').slice(1, 4).join(' | '),
        });
      };
      window.addEventListener('scroll', onScroll, { capture: true, passive: true });
      document.addEventListener('scroll', onScroll, { capture: true, passive: true });
      console.log('watcher installed, scrollY=' + window.scrollY);
    }""")

    print('BEFORE click: scrollY=', page.evaluate('() => window.scrollY'))

    cards = page.locator('a[href^="/listings/"]')
    for i in range(cards.count()):
        box = cards.nth(i).bounding_box()
        if box and 0 < box['y'] < 80:
            print(f'  clicking card {i} at y={box["y"]:.0f}')
            cards.nth(i).click()
            break

    page.wait_for_selector('[role="dialog"][aria-modal="true"]', timeout=5000)
    page.wait_for_timeout(500)

    log = page.evaluate('() => window.__scrollLog')
    print(f'scroll events ({len(log)}):')
    for e in log[:20]:
        print('  ', e)
    print('body.top now =', page.evaluate('() => document.body.style.top'))

    browser.close()

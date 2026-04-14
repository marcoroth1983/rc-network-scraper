import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import {
  MemoryRouter,
  Routes,
  Route,
  createMemoryRouter,
  RouterProvider,
} from 'react-router-dom';
import ListingDetailModal from '../ListingDetailModal';

// ---------------------------------------------------------------------------
// Minimal child content for the modal so we can identify it in the tree
// ---------------------------------------------------------------------------
function ModalContent({ id }: { id?: string }) {
  return <div data-testid={`modal-content-${id ?? 'default'}`}>content</div>;
}

// ---------------------------------------------------------------------------
// Helper: render modal under a MemoryRouter at a given path + state
// ---------------------------------------------------------------------------
function renderModal(opts: {
  path?: string;
  state?: object;
  children?: React.ReactNode;
}) {
  const { path = '/listings/42', state = {}, children = <ModalContent /> } = opts;
  return render(
    <MemoryRouter
      initialEntries={[{ pathname: path, search: '', hash: '', state }]}
      initialIndex={0}
    >
      <Routes>
        <Route
          path="/listings/:id"
          element={<ListingDetailModal>{children}</ListingDetailModal>}
        />
      </Routes>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Case 3 — close via navigate(-1) (non-direct-hit): modal unmounts
// ---------------------------------------------------------------------------
describe('ListingDetailModal — case 3: close via navigate(-1)', () => {
  it('modal unmounts after close button click (non-direct-hit)', async () => {
    // Set up two history entries: first '/', then '/listings/42'
    render(
      <MemoryRouter
        initialEntries={[
          { pathname: '/' },
          {
            pathname: '/listings/42',
            search: '',
            hash: '',
            state: {
              background: { pathname: '/', search: '', hash: '', state: null, key: '' },
            },
          },
        ]}
        initialIndex={1}
      >
        <Routes>
          <Route path="/" element={<div data-testid="listings-page">Listings</div>} />
          <Route
            path="/listings/:id"
            element={
              <ListingDetailModal>
                <ModalContent />
              </ListingDetailModal>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByRole('dialog')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /schließen/i }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull();
    });
    // Listings page should be visible again
    expect(screen.getByTestId('listings-page')).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Case 4 — direct-hit close: uses navigate('/', { replace: true })
// ---------------------------------------------------------------------------
describe('ListingDetailModal — case 4: direct-hit close', () => {
  it('navigates to "/" and unmounts modal when isDirectHit is true', async () => {
    const routes = [
      {
        path: '/',
        element: <div data-testid="listings-page">Listings</div>,
      },
      {
        path: '/listings/:id',
        element: (
          <ListingDetailModal>
            <ModalContent />
          </ListingDetailModal>
        ),
      },
    ];

    const router = createMemoryRouter(routes, {
      initialEntries: [
        {
          pathname: '/listings/42',
          search: '',
          hash: '',
          // Synthesize the state that DirectHitDetailRedirect would produce
          state: {
            background: { pathname: '/', search: '', hash: '', state: null, key: '' },
            isDirectHit: true,
          },
        },
      ],
      initialIndex: 0,
    });

    render(<RouterProvider router={router} />);

    // Modal should be visible
    expect(screen.getByRole('dialog')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /schließen/i }));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/');
      expect(screen.queryByRole('dialog')).toBeNull();
    });
  });
});

// ---------------------------------------------------------------------------
// Case 5 — scroll is preserved across modal open/close
// ---------------------------------------------------------------------------
describe('ListingDetailModal — case 5: scroll preservation', () => {
  it('preserves document scroll position across modal open/close', () => {
    // Primary assertion: the user's scroll position must survive the modal lifecycle.
    // jsdom does not honour setting scrollTop on documentElement (no scrollable overflow),
    // so we intercept the prototype setter to simulate a non-zero document scroll that
    // the modal code must not touch.
    let docScrollTop = 1000;
    const originalDescriptor = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollTop');
    const targetElement = document.documentElement;
    Object.defineProperty(Element.prototype, 'scrollTop', {
      configurable: true,
      get() {
        return this === targetElement ? docScrollTop : 0;
      },
      set(value: number) {
        if (this === targetElement) {
          docScrollTop = value;
        }
      },
    });

    // Secondary guard: modal must not programmatically scroll the window.
    const scrollToSpy = vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined);

    try {
      const { unmount } = renderModal({});
      expect(screen.getByRole('dialog')).toBeTruthy();
      unmount();

      // Primary: document scroll position unchanged after modal lifecycle.
      expect(document.documentElement.scrollTop).toBe(1000);
      // Secondary: modal never called window.scrollTo.
      expect(scrollToSpy).not.toHaveBeenCalled();
    } finally {
      scrollToSpy.mockRestore();
      if (originalDescriptor) {
        Object.defineProperty(Element.prototype, 'scrollTop', originalDescriptor);
      }
    }
  });
});

// ---------------------------------------------------------------------------
// Case 6 — body.style.overflow lock/unlock + overscroll-behavior inline style
// ---------------------------------------------------------------------------
describe('ListingDetailModal — case 6: body overflow lock/unlock', () => {
  it('locks body overflow on mount and restores it on unmount', () => {
    // jsdom starts with '' — capture it as the expected "pre-mount" value
    const preMountOverflow = document.body.style.overflow;

    const { unmount } = renderModal({});

    // Body should be locked while modal is mounted
    expect(document.body.style.overflow).toBe('hidden');

    unmount();

    // Body overflow should be restored to the pre-mount value
    expect(document.body.style.overflow).toBe(preMountOverflow);
  });

  it('modal wrapper has overscroll-behavior: contain in its inline style', () => {
    renderModal({});
    const dialog = screen.getByRole('dialog');
    // jsdom reflects inline styles as set via the style attribute
    expect(dialog.style.overscrollBehavior).toBe('contain');
  });
});

// ---------------------------------------------------------------------------
// Case 7 — scroll-lock survives re-render (A → nested B navigation)
// ---------------------------------------------------------------------------
describe('ListingDetailModal — case 7: scroll-lock stays through re-render', () => {
  beforeEach(() => {
    document.body.style.overflow = '';
  });

  afterEach(() => {
    document.body.style.overflow = '';
  });

  it('body overflow stays "hidden" during a pathname change and restores on unmount', () => {
    const { rerender, unmount } = renderModal({
      children: <ModalContent id="42" />,
    });

    expect(document.body.style.overflow).toBe('hidden');

    // Simulate a nested navigation by re-rendering with different children
    // (in the real app the router would change location.pathname,
    //  but testing the effect-with-empty-deps contract is enough)
    rerender(
      <MemoryRouter
        initialEntries={[
          {
            pathname: '/listings/99',
            search: '',
            hash: '',
            state: {
              background: { pathname: '/', search: '', hash: '', state: null, key: '' },
            },
          },
        ]}
        initialIndex={0}
      >
        <Routes>
          <Route
            path="/listings/:id"
            element={
              <ListingDetailModal>
                <ModalContent id="99" />
              </ListingDetailModal>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    // Still locked — the empty-deps effect must NOT toggle between renders
    expect(document.body.style.overflow).toBe('hidden');

    unmount();

    // Restored only after full unmount
    expect(document.body.style.overflow).toBe('');
  });
});

// ---------------------------------------------------------------------------
// Case 17 — modal scroll resets on nested navigation (A → B)
// ---------------------------------------------------------------------------
// The implementation: useEffect(() => { if (wrapperRef.current) wrapperRef.current.scrollTop = 0; }, [location.pathname])
//
// To test this, we need a navigation that changes location.pathname while keeping
// the SAME modal instance mounted. We use createMemoryRouter + RouterProvider
// and call router.navigate() to perform an in-place pathname change.
//
// jsdom does not implement scroll, so we intercept the prototype setter to capture
// assignments to .scrollTop.

describe('ListingDetailModal — case 17: scroll resets on pathname change', () => {
  it('assigns wrapperRef.scrollTop = 0 when navigating from /listings/42 to /listings/99', async () => {
    const scrollTopAssignments: Array<{ element: Element; value: number }> = [];

    // Intercept .scrollTop setter on the prototype to capture all assignments
    const originalDescriptor = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      'scrollTop',
    );
    Object.defineProperty(HTMLElement.prototype, 'scrollTop', {
      configurable: true,
      get() {
        return originalDescriptor?.get?.call(this) ?? 0;
      },
      set(v: number) {
        scrollTopAssignments.push({ element: this as Element, value: v });
        originalDescriptor?.set?.call(this, v);
      },
    });

    try {
      const router = createMemoryRouter(
        [
          {
            path: '/listings/:id',
            element: (
              <ListingDetailModal>
                <ModalContent />
              </ListingDetailModal>
            ),
          },
        ],
        {
          initialEntries: [
            {
              pathname: '/listings/42',
              search: '',
              hash: '',
              state: {
                background: { pathname: '/', search: '', hash: '', state: null, key: '' },
              },
            },
          ],
          initialIndex: 0,
        },
      );

      render(<RouterProvider router={router} />);

      // Wait for modal to mount
      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeTruthy();
      });

      // Clear assignments from the initial mount
      scrollTopAssignments.length = 0;

      // Navigate to /listings/99 — same route, different param
      // This changes location.pathname and triggers the [location.pathname] effect
      await act(async () => {
        router.navigate('/listings/99', {
          state: {
            background: { pathname: '/', search: '', hash: '', state: null, key: '' },
          },
        });
      });

      // The effect should have assigned scrollTop = 0 to the [role="dialog"] wrapper
      await waitFor(() => {
        const dialogAssignments = scrollTopAssignments.filter(
          (a) => (a.element as HTMLElement).getAttribute('role') === 'dialog' && a.value === 0,
        );
        expect(dialogAssignments.length).toBeGreaterThan(0);
      });
    } finally {
      // Always restore original descriptor
      if (originalDescriptor) {
        Object.defineProperty(HTMLElement.prototype, 'scrollTop', originalDescriptor);
      } else {
        // Delete our override if there was no original
        delete (HTMLElement.prototype as unknown as Record<string, unknown>).scrollTop;
      }
    }
  });
});

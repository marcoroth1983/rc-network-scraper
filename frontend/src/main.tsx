import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'

// Disable browser-native scroll restoration. We manage scroll preservation
// ourselves via sessionStorage (see useListingsScrollPreservation) so behaviour
// is identical across Chrome, Firefox, Safari, and iOS webview. Browser-native
// restoration with html{overflow:hidden} modal locks is unreliable across
// engines and produced the "back button scrolls to wrong position" bug.
if (typeof history !== 'undefined' && 'scrollRestoration' in history) {
  history.scrollRestoration = 'manual'
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js')
  })
}

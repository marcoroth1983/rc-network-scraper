import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

function GoogleIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4"/>
      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18A10.97 10.97 0 001 12c0 1.78.43 3.46 1.18 4.93l3.66-2.84z" fill="#FBBC05"/>
      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
    </svg>
  )
}

export default function LoginPage() {
  const [params] = useSearchParams()
  const error = params.get('error')
  const email = params.get('email')
  const [privacyOpen, setPrivacyOpen] = useState(false)
  const [loggingIn, setLoggingIn] = useState(false)

  return (
    <div className="relative min-h-screen flex items-center justify-center px-4 overflow-hidden"
         style={{ background: '#0f0f23' }}>


      {/* Aurora gradient blobs */}
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-[-20%] left-[10%] w-[60%] h-[60%] rounded-full opacity-25 blur-[80px] animate-pulse"
             style={{ background: 'radial-gradient(circle, rgba(99,102,241,0.5), transparent 70%)' }} />
        <div className="absolute bottom-[-10%] right-[10%] w-[50%] h-[50%] rounded-full opacity-20 blur-[80px] animate-pulse"
             style={{ background: 'radial-gradient(circle, rgba(236,72,153,0.4), transparent 70%)', animationDelay: '2s' }} />
        <div className="absolute top-[30%] right-[30%] w-[40%] h-[40%] rounded-full opacity-[0.15] blur-[60px] animate-pulse"
             style={{ background: 'radial-gradient(circle, rgba(45,212,191,0.3), transparent 70%)', animationDelay: '4s' }} />
      </div>

      {/* Card */}
      <div className="relative w-full max-w-[420px] rounded-3xl p-12 text-center space-y-7 border"
           style={{
             background: 'rgba(30, 30, 60, 0.7)',
             backdropFilter: 'blur(24px) saturate(1.2)',
             WebkitBackdropFilter: 'blur(24px) saturate(1.2)',
             borderColor: 'rgba(255,255,255,0.14)',
             boxShadow: '0 0 80px rgba(99,102,241,0.12), 0 8px 32px rgba(0,0,0,0.4)',
           }}>

        {/* Icon */}
        <div className="inline-flex items-center justify-center w-[60px] h-[60px] rounded-2xl border"
             style={{
               background: 'linear-gradient(135deg, rgba(99,102,241,0.3), rgba(236,72,153,0.3))',
               borderColor: 'rgba(255,255,255,0.1)',
             }}>
          <svg className="w-7 h-7" style={{ color: '#A78BFA' }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <circle cx="11" cy="11" r="7" />
            <path d="M21 21l-4.35-4.35" strokeLinecap="round" />
          </svg>
        </div>

        <div>
          <h1 className="text-[28px] font-bold tracking-tight" style={{ color: '#F8FAFC' }}>
            RC-Network Scout
          </h1>
          <p className="text-sm mt-1.5" style={{ color: 'rgba(248,250,252,0.5)' }}>
            Dein persönlicher RC-Flohmarkt-Scout
          </p>
        </div>

        {error === 'not_approved' && (
          <div className="rounded-xl p-4 text-sm text-left border"
               style={{
                 background: 'rgba(251,191,36,0.08)',
                 borderColor: 'rgba(251,191,36,0.2)',
                 color: '#FDE68A',
               }}>
            <strong>Kein Zugang.</strong>
            {email && <> Dein Account ({email}) wurde noch nicht freigeschaltet.</>}
          </div>
        )}

        {error === 'denied' && (
          <div className="rounded-xl p-4 text-sm text-left border"
               style={{
                 background: 'rgba(239,68,68,0.08)',
                 borderColor: 'rgba(239,68,68,0.2)',
                 color: '#FCA5A5',
               }}>
            <strong>Anmeldung abgebrochen.</strong> Die Google-Anmeldung wurde abgebrochen oder abgelehnt.
          </div>
        )}

        <a href="/api/auth/google"
           className="flex items-center justify-center gap-3 w-full rounded-xl px-4 py-3.5 text-sm font-semibold no-underline border transition-all duration-200"
           style={{
             background: loggingIn ? 'rgba(255,255,255,0.04)' : 'rgba(255,255,255,0.08)',
             borderColor: 'rgba(255,255,255,0.12)',
             color: loggingIn ? 'rgba(226,232,240,0.4)' : '#E2E8F0',
             pointerEvents: loggingIn ? 'none' : 'auto',
           }}
           onClick={() => setLoggingIn(true)}
           onMouseOver={e => { if (!loggingIn) { e.currentTarget.style.background = 'rgba(255,255,255,0.14)'; e.currentTarget.style.boxShadow = '0 0 20px rgba(99,102,241,0.15)'; } }}
           onMouseOut={e => { if (!loggingIn) { e.currentTarget.style.background = 'rgba(255,255,255,0.08)'; e.currentTarget.style.boxShadow = 'none'; } }}
        >
          <GoogleIcon />
          {loggingIn ? 'Weiterleitung…' : error === 'not_approved' ? 'Mit anderem Account anmelden' : 'Mit Google anmelden'}
        </a>

        <div className="flex items-center gap-3">
          <span className="flex-1 h-px" style={{ background: 'rgba(255,255,255,0.08)' }} />
          <svg className="w-4 h-4" style={{ color: 'rgba(255,255,255,0.15)' }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
          </svg>
          <span className="flex-1 h-px" style={{ background: 'rgba(255,255,255,0.08)' }} />
        </div>

        <p className="text-xs" style={{ color: 'rgba(248,250,252,0.3)' }}>
          Zugang nur für freigeschaltete Mitglieder.
        </p>
      </div>

      {/* Footer */}
      <div
        className="fixed bottom-0 left-0 right-0 flex items-center justify-center py-3"
        style={{
          background: 'rgba(15,15,35,0.85)',
          backdropFilter: 'blur(12px)',
          borderTop: '1px solid rgba(255,255,255,0.06)',
        }}
      >
        <button
          type="button"
          onClick={() => setPrivacyOpen(true)}
          className="text-xs transition-colors"
          style={{ color: 'rgba(248,250,252,0.3)' }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.color = 'rgba(248,250,252,0.6)' }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.color = 'rgba(248,250,252,0.3)' }}
        >
          Datenschutzerklärung
        </button>
      </div>

      {/* Privacy modal */}
      {privacyOpen && (
        <>
          <div
            className="fixed inset-0 z-50"
            style={{ background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)' }}
            onClick={() => setPrivacyOpen(false)}
          />
          <div
            className="fixed inset-x-4 top-12 bottom-12 z-50 max-w-xl mx-auto rounded-2xl flex flex-col overflow-hidden"
            style={{
              background: 'rgba(18,18,40,0.98)',
              border: '1px solid rgba(255,255,255,0.1)',
              boxShadow: '0 24px 64px rgba(0,0,0,0.6)',
            }}
          >
            {/* Modal header */}
            <div
              className="flex items-center justify-between px-6 py-4 flex-shrink-0"
              style={{ borderBottom: '1px solid rgba(255,255,255,0.07)' }}
            >
              <h2 className="text-sm font-semibold" style={{ color: '#F8FAFC' }}>Datenschutzerklärung</h2>
              <button
                type="button"
                onClick={() => setPrivacyOpen(false)}
                className="w-7 h-7 flex items-center justify-center rounded-full transition-colors"
                style={{ background: 'rgba(255,255,255,0.07)', color: 'rgba(248,250,252,0.5)' }}
                aria-label="Schließen"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path d="M18 6L6 18M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Modal body */}
            <div className="flex-1 overflow-y-auto px-6 py-5 text-sm space-y-4" style={{ color: 'rgba(248,250,252,0.65)', lineHeight: '1.7' }}>
              <p>
                Diese Anwendung ist ein privates Hobby-Projekt und nicht öffentlich zugänglich. Der Zugang ist ausschließlich auf freigeschaltete Personen beschränkt.
              </p>
              <h3 className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'rgba(248,250,252,0.35)' }}>Erhobene Daten</h3>
              <p>
                Bei der Anmeldung über Google OAuth werden folgende Daten gespeichert: Google-ID, E-Mail-Adresse und Name. Diese Daten werden ausschließlich zur Authentifizierung verwendet und nicht an Dritte weitergegeben.
              </p>
              <h3 className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'rgba(248,250,252,0.35)' }}>Hosting & Betrieb</h3>
              <p>
                Die Anwendung wird auf einem privaten VPS betrieben, der ausschließlich dem Betreiber zugänglich ist. Es werden keine Nutzerdaten zu Werbezwecken verarbeitet oder verkauft.
              </p>
              <h3 className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'rgba(248,250,252,0.35)' }}>Kontakt</h3>
              <p>
                Bei Fragen zur Datenschutzerklärung wenden Sie sich an den Betreiber dieser Anwendung.
              </p>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

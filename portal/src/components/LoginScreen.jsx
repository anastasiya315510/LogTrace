import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'

export default function LoginScreen({ onLogin }) {
  const [key, setKey] = useState('')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    const trimmed = key.trim()
    if (!trimmed) return
    setLoading(true)
    setError(null)
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 5000)
    try {
      const res = await fetch('/demo/status', {
        headers: { 'X-API-Key': trimmed },
        signal: controller.signal,
      })
      if (res.status === 401 || res.status === 403) setError('Invalid API key.')
      else if (!res.ok) setError(`Server error: ${res.status}`)
      else onLogin(trimmed)
    } catch (e) {
      if (e.name === 'AbortError') setError('API did not respond — is the server running?')
      else setError('Could not reach the API. Is the server running?')
    } finally {
      clearTimeout(timeout)
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4" style={{ background: 'var(--bg)' }}>
      <div className="w-full max-w-sm">

        {/* Logo */}
        <div className="text-center mb-8">
          <div
            className="inline-flex items-center justify-center w-16 h-16 rounded-2xl mb-5"
            style={{ background: 'rgba(127,157,181,0.1)', border: '1px solid rgba(127,157,181,0.2)', boxShadow: '0 4px 28px rgba(127,157,181,0.18)' }}
          >
            <img src="icon.svg" alt="LogTrace" style={{ width: 36, height: 36 }} />
          </div>
          <h1 className="text-3xl font-extrabold tracking-tight" style={{ color: 'var(--text)' }}>
            LogTrace
          </h1>
          <p className="text-sm font-medium mt-1.5" style={{ color: 'var(--text-2)' }}>AI Log Intelligence</p>
        </div>

        {/* Card */}
        <form
          onSubmit={handleSubmit}
          className="rounded-2xl p-7 space-y-5"
          style={{ background: 'var(--card)', boxShadow: '0 8px 32px rgba(0,0,0,0.35), inset 0 0 0 1px var(--border)' }}
        >
          <div>
            <label className="block text-xs font-semibold uppercase tracking-widest mb-2.5" style={{ color: 'var(--text-2)' }}>
              API Key
            </label>
            <input
              type="password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="Enter your API key"
              autoFocus
              className="w-full rounded-xl px-4 py-3 text-sm placeholder-[var(--text-3)] focus:outline-none transition-all"
              style={{
                background: 'var(--card-2)',
                color: 'var(--text)',
                boxShadow: 'inset 0 0 0 1px var(--border)',
              }}
              onFocus={(e) => { e.currentTarget.style.boxShadow = `inset 0 0 0 1.5px var(--info)` }}
              onBlur={(e) => { e.currentTarget.style.boxShadow = 'inset 0 0 0 1px var(--border)' }}
            />
          </div>

          {error && (
            <div className="flex items-center gap-2 rounded-lg px-3 py-2.5" style={{ background: 'rgba(196,125,109,0.12)', boxShadow: 'inset 0 0 0 1px rgba(196,125,109,0.25)' }}>
              <AlertTriangle size={13} strokeWidth={2} style={{ color: 'var(--error)', flexShrink: 0 }} />
              <p className="text-xs font-medium" style={{ color: 'var(--error)' }}>{error}</p>
            </div>
          )}

          <button
            type="submit"
            disabled={!key.trim() || loading}
            className="w-full py-3 rounded-xl text-sm font-bold transition-all disabled:cursor-not-allowed"
            style={{
              background: !key.trim() || loading ? 'var(--card-2)' : 'var(--info)',
              color: !key.trim() || loading ? 'var(--text-2)' : 'var(--bg)',
              opacity: !key.trim() || loading ? 0.6 : 1,
            }}
          >
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <span className="w-4 h-4 border-2 border-current/30 border-t-current rounded-full animate-spin" />
                Verifying…
              </span>
            ) : 'Enter Portal'}
          </button>

        </form>
      </div>
    </div>
  )
}
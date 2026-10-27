import { useState } from 'react'
import { Play, Zap, RotateCcw, LogOut } from 'lucide-react'
import { startDemo, triggerCascade, resetDemo, getDemoStatus } from '../api'

const PHASE_CONFIG = {
  idle:    { text: '#879477', bg: 'rgba(135,148,119,0.12)', ring: 'rgba(135,148,119,0.2)',  dot: '#879477', pulse: false },
  normal:  { text: '#7F9DB5', bg: 'rgba(127,157,181,0.12)', ring: 'rgba(127,157,181,0.25)', dot: '#7F9DB5', pulse: false },
  cascade: { text: '#C47D6D', bg: 'rgba(196,125,109,0.15)', ring: 'rgba(196,125,109,0.3)',  dot: '#C47D6D', pulse: true  },
}

const SCENARIOS = [
  { id: 'pool_exhaustion', label: 'DB Pool Exhaustion' },
  { id: 'memory_leak',     label: 'Memory Leak / OOM'  },
  { id: 'slow_query',      label: 'Deadlock / Slow Query' },
]

export default function DemoPanel({ demoStatus, onStatusChange, onLogout }) {
  const [loading, setLoading] = useState(null)
  const [scenario, setScenario] = useState('pool_exhaustion')

  const phase = demoStatus?.phase ?? 'idle'
  const eventsPushed = demoStatus?.events_pushed ?? 0
  const pc = PHASE_CONFIG[phase] ?? PHASE_CONFIG.idle

  async function refreshStatus() {
    try { const s = await getDemoStatus(); onStatusChange(s) } catch {}
  }

  async function handleStart() {
    setLoading('start')
    try {
      await startDemo()
      await refreshStatus()
      setTimeout(async () => {
        try { await triggerCascade(scenario); await refreshStatus() } catch {}
      }, 2000)
    } catch (e) { console.error('startDemo failed', e) }
    finally { setLoading(null) }
  }

  async function handleCascade() {
    setLoading('cascade')
    try { await triggerCascade(scenario); await refreshStatus() }
    catch (e) { console.error('triggerCascade failed', e) }
    finally { setLoading(null) }
  }

  async function handleReset() {
    setLoading('reset')
    try { await resetDemo(); await refreshStatus() }
    catch (e) { console.error('resetDemo failed', e) }
    finally { setLoading(null) }
  }

  const startDisabled   = phase !== 'idle' || loading !== null
  const cascadeDisabled = phase === 'cascade' || phase === 'idle' || loading !== null
  const resetDisabled   = loading !== null

  return (
    <header
      className="sticky top-0 z-20 px-6 py-3.5 flex items-center justify-between"
      style={{ background: 'var(--card)', borderBottom: '1px solid var(--border)', boxShadow: '0 2px 20px rgba(0,0,0,0.35)' }}
    >
      {/* Branding */}
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-xl flex items-center justify-center"
          style={{ background: 'rgba(127,157,181,0.1)', border: '1px solid rgba(127,157,181,0.2)', boxShadow: '0 0 16px rgba(127,157,181,0.15)' }}>
          <img src="icon.svg" alt="LogTrace" style={{ width: 20, height: 20 }} />
        </div>
        <div>
          <span className="font-bold text-lg tracking-tight leading-none" style={{ color: 'var(--text)' }}>LogTrace</span>
          <p className="text-xs font-medium leading-none mt-1" style={{ color: 'var(--text-2)' }}>AI Log Intelligence</p>
        </div>
      </div>

      {/* Phase badge */}
      <div className="flex flex-col items-center gap-1">
        <span
          className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wider"
          style={{ color: pc.text, background: pc.bg, boxShadow: `inset 0 0 0 1px ${pc.ring}` }}
        >
          <span className={`w-1.5 h-1.5 rounded-full ${pc.pulse ? 'animate-pulse' : ''}`} style={{ backgroundColor: pc.dot }} />
          {phase}
        </span>
        {eventsPushed > 0 && (
          <span className="text-xs tabular-nums" style={{ color: 'var(--text-3)' }}>{eventsPushed.toLocaleString()} events</span>
        )}
      </div>

      {/* Controls */}
      <div className="flex items-center gap-2">
        <HeaderBtn onClick={handleStart} disabled={startDisabled} loading={loading === 'start'} loadingLabel="Starting…" color="var(--success)" icon={<Play size={13} strokeWidth={2.5} />}>
          Start Demo
        </HeaderBtn>

        {/* Scenario selector + inject button */}
        <div className="flex items-center rounded-lg overflow-hidden" style={{ boxShadow: 'inset 0 0 0 1px var(--border)' }}>
          <select
            value={scenario}
            onChange={(e) => setScenario(e.target.value)}
            disabled={phase === 'cascade' || loading !== null}
            className="text-xs font-medium px-2.5 py-1.5 appearance-none cursor-pointer focus:outline-none"
            style={{
              background: 'var(--card-2)',
              color: 'var(--text-2)',
              borderRight: '1px solid var(--border)',
            }}
          >
            {SCENARIOS.map(s => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
          <button
            onClick={handleCascade}
            disabled={cascadeDisabled || loading !== null}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold transition-all disabled:cursor-not-allowed"
            style={{
              background: cascadeDisabled ? 'var(--card-2)' : 'var(--warning)',
              color: cascadeDisabled ? 'var(--text-2)' : 'var(--bg)',
              opacity: cascadeDisabled ? 0.45 : 1,
            }}
          >
            {loading === 'cascade' ? (
              <><span className="w-3 h-3 border border-current/40 border-t-current rounded-full animate-spin" />Injecting…</>
            ) : (
              <><Zap size={13} strokeWidth={2.5} />Inject</>
            )}
          </button>
        </div>
        <HeaderBtn onClick={handleReset} disabled={resetDisabled} loading={loading === 'reset'} loadingLabel="Resetting…" neutral icon={<RotateCcw size={13} strokeWidth={2.5} />}>
          Reset
        </HeaderBtn>

        <div className="w-px h-5 mx-1" style={{ background: 'var(--border)' }} />

        <button
          onClick={onLogout}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
          style={{ color: 'var(--text-2)', background: 'transparent' }}
          onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text)'; e.currentTarget.style.background = 'var(--card-2)' }}
          onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-2)'; e.currentTarget.style.background = 'transparent' }}
        >
          <LogOut size={13} strokeWidth={2} />
          <span>Logout</span>
        </button>
      </div>
    </header>
  )
}

function HeaderBtn({ onClick, disabled, loading, loadingLabel, children, color, neutral, icon }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all disabled:cursor-not-allowed"
      style={{
        background: neutral ? 'var(--card-2)' : disabled ? 'var(--card-2)' : color,
        color: neutral || disabled ? 'var(--text-2)' : 'var(--bg)',
        boxShadow: neutral ? 'inset 0 0 0 1px var(--border)' : 'none',
        opacity: disabled ? 0.45 : 1,
      }}
    >
      {loading ? (
        <><span className="w-3 h-3 border border-current/40 border-t-current rounded-full animate-spin" />{loadingLabel}</>
      ) : (
        <>{icon}{children}</>
      )}
    </button>
  )
}
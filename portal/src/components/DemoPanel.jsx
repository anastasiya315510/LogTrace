import { useState } from 'react'
import { startDemo, triggerCascade, resetDemo, getDemoStatus } from '../api'

const PHASE_BADGE = {
  idle: 'bg-slate-700 text-slate-300',
  normal: 'bg-blue-600 text-white',
  cascade: 'bg-red-600 text-white animate-pulse',
}

export default function DemoPanel({ demoStatus, onStatusChange }) {
  const [loading, setLoading] = useState(null)

  const phase = demoStatus?.phase ?? 'idle'
  const eventsPushed = demoStatus?.events_pushed ?? 0

  async function refreshStatus() {
    try {
      const s = await getDemoStatus()
      onStatusChange(s)
    } catch {}
  }

  async function handleStart() {
    setLoading('start')
    try {
      await startDemo()
      await refreshStatus()
      // Trigger cascade after 2s
      setTimeout(async () => {
        try {
          await triggerCascade()
          await refreshStatus()
        } catch {}
      }, 2000)
    } catch (e) {
      console.error('startDemo failed', e)
    } finally {
      setLoading(null)
    }
  }

  async function handleCascade() {
    setLoading('cascade')
    try {
      await triggerCascade()
      await refreshStatus()
    } catch (e) {
      console.error('triggerCascade failed', e)
    } finally {
      setLoading(null)
    }
  }

  async function handleReset() {
    setLoading('reset')
    try {
      await resetDemo()
      await refreshStatus()
    } catch (e) {
      console.error('resetDemo failed', e)
    } finally {
      setLoading(null)
    }
  }

  const startDisabled = phase !== 'idle' || loading !== null
  const cascadeDisabled = phase === 'cascade' || phase === 'idle' || loading !== null
  const resetDisabled = loading !== null

  return (
    <header className="bg-slate-900 border-b border-slate-700 px-6 py-3 flex items-center justify-between">
      {/* Left: branding */}
      <div>
        <span className="text-white font-bold text-lg">⚡ NemoTrace</span>
        <p className="text-slate-400 text-xs mt-0.5">AI Log Intelligence</p>
      </div>

      {/* Center: phase badge */}
      <div className="flex flex-col items-center gap-1">
        <span
          className={`px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wide ${
            PHASE_BADGE[phase] ?? PHASE_BADGE.idle
          }`}
        >
          {phase}
        </span>
        {eventsPushed > 0 && (
          <span className="text-slate-400 text-xs">{eventsPushed} events pushed</span>
        )}
      </div>

      {/* Right: control buttons */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleStart}
          disabled={startDisabled}
          className="px-4 py-1.5 rounded text-sm font-medium bg-green-700 hover:bg-green-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-white"
        >
          {loading === 'start' ? 'Starting…' : 'Start Demo'}
        </button>
        <button
          onClick={handleCascade}
          disabled={cascadeDisabled}
          className="px-4 py-1.5 rounded text-sm font-medium bg-orange-700 hover:bg-orange-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-white"
        >
          {loading === 'cascade' ? 'Injecting…' : 'Inject Cascade'}
        </button>
        <button
          onClick={handleReset}
          disabled={resetDisabled}
          className="px-4 py-1.5 rounded text-sm font-medium bg-slate-700 hover:bg-slate-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-white"
        >
          {loading === 'reset' ? 'Resetting…' : 'Reset'}
        </button>
      </div>
    </header>
  )
}
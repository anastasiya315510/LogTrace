import { useState } from 'react'
import { Maximize2, X } from 'lucide-react'
import { createPortal } from 'react-dom'

const STEP_COLORS = [
  { color: 'var(--error)',   bg: 'rgba(196,125,109,0.15)', ring: 'rgba(196,125,109,0.3)'  },
  { color: 'var(--warning)', bg: 'rgba(201,160,90,0.15)',  ring: 'rgba(201,160,90,0.3)'   },
  { color: 'var(--alt)',     bg: 'rgba(135,148,119,0.15)', ring: 'rgba(135,148,119,0.3)'  },
  { color: 'var(--info)',    bg: 'rgba(127,157,181,0.15)', ring: 'rgba(127,157,181,0.3)'  },
]

function getStep(index) { return STEP_COLORS[index] ?? STEP_COLORS[STEP_COLORS.length - 1] }

function formatTimestamp(ts) {
  if (!ts) return null
  try {
    const d = new Date(ts)
    const hh = String(d.getUTCHours()).padStart(2, '0')
    const mm = String(d.getUTCMinutes()).padStart(2, '0')
    const ss = String(d.getUTCSeconds()).padStart(2, '0')
    return `${hh}:${mm}:${ss} UTC`
  } catch { return ts }
}

function ChainItems({ chain, showMessage }) {
  if (!chain || chain.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-2)' }}>
        No cascade data yet
      </div>
    )
  }
  return (
    <div className="relative">
      {chain.map((item, idx) => {
        const s = getStep(idx)
        const ts = formatTimestamp(item.timestamp)
        return (
          <div key={idx} className="relative flex gap-4 pb-5 last:pb-0">
            {idx < chain.length - 1 && (
              <div className="absolute left-[15px] top-8 bottom-0 w-0.5"
                style={{ background: `linear-gradient(to bottom, ${s.ring}, var(--border-2))` }} />
            )}
            <div className="flex-shrink-0 z-10">
              <div className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold"
                style={{ background: s.bg, color: s.color, boxShadow: `inset 0 0 0 1px ${s.ring}` }}>
                {idx + 1}
              </div>
            </div>
            <div className="flex-1 min-w-0 pt-0.5">
              <span className="inline-block text-xs font-semibold px-2 py-0.5 rounded-lg mb-1 font-mono"
                style={{ background: 'var(--card-2)', color: 'var(--text)', boxShadow: 'inset 0 0 0 1px var(--border)' }}>
                {item.service ?? '—'}
              </span>
              {item.error && (
                <p className="text-xs truncate leading-tight mt-0.5" style={{ color: 'var(--error)', opacity: 0.85 }} title={item.error}>
                  {item.error}
                </p>
              )}
              {showMessage && item.message && (
                <p className="text-xs leading-relaxed mt-1" style={{ color: 'var(--text-2)' }}>
                  {item.message}
                </p>
              )}
              {ts && (
                <p className="text-xs mt-1 font-mono" style={{ color: 'var(--text-3)' }}>{ts}</p>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default function CascadeChain({ chain }) {
  const [fullscreen, setFullscreen] = useState(false)

  return (
    <>
      <div className="rounded-2xl flex flex-col"
        style={{ background: 'var(--card)', boxShadow: 'inset 0 0 0 1px var(--border)' }}>

        <div className="flex items-center justify-between px-5 pt-5 pb-3">
          <h3 className="text-sm font-semibold uppercase tracking-widest" style={{ color: 'var(--text-2)' }}>
            Cascade Chain
          </h3>
          <button onClick={() => setFullscreen(true)} style={{ color: 'var(--text-3)' }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text-2)' }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-3)' }}>
            <Maximize2 size={14} strokeWidth={2} />
          </button>
        </div>

        <div className="expand-on-print px-5 pb-5 overflow-y-auto" style={{ maxHeight: '14rem' }}>
          <ChainItems chain={chain} showMessage={false} />
        </div>
      </div>

      {fullscreen && createPortal(
        <div className="fixed inset-0 z-50 flex items-start justify-center p-6 pt-16 overflow-y-auto"
          style={{ background: 'rgba(20,23,26,0.85)', backdropFilter: 'blur(6px)' }}
          onClick={(e) => { if (e.target === e.currentTarget) setFullscreen(false) }}>
          <div className="w-full max-w-2xl rounded-2xl flex flex-col"
            style={{ background: 'var(--card)', boxShadow: '0 24px 64px rgba(0,0,0,0.5), inset 0 0 0 1px var(--border)' }}>
            <div className="flex items-center justify-between px-6 pt-6 pb-4"
              style={{ borderBottom: '1px solid var(--border)' }}>
              <h3 className="text-sm font-semibold uppercase tracking-widest" style={{ color: 'var(--text-2)' }}>
                Cascade Chain
              </h3>
              <button onClick={() => setFullscreen(false)} style={{ color: 'var(--text-3)' }}
                onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text)' }}
                onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-3)' }}>
                <X size={16} strokeWidth={2} />
              </button>
            </div>
            <div className="px-6 py-5">
              <ChainItems chain={chain} showMessage={true} />
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  )
}
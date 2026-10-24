import { useState } from 'react'
import { Link2, Maximize2, X, Wrench, ShieldAlert, FileText, ExternalLink } from 'lucide-react'
import { createPortal } from 'react-dom'

const TYPE_STYLE = {
  remediation:   { text: 'var(--success)', bg: 'rgba(143,181,160,0.12)', ring: 'rgba(143,181,160,0.25)', icon: <Wrench size={11} strokeWidth={2.5} /> },
  vulnerability: { text: 'var(--error)',   bg: 'rgba(196,125,109,0.12)', ring: 'rgba(196,125,109,0.25)', icon: <ShieldAlert size={11} strokeWidth={2.5} /> },
  other:         { text: 'var(--info)',    bg: 'rgba(127,157,181,0.12)', ring: 'rgba(127,157,181,0.25)', icon: <FileText size={11} strokeWidth={2.5} /> },
}

function TypeBadge({ type }) {
  const s = TYPE_STYLE[type] ?? TYPE_STYLE.other
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold uppercase tracking-wider"
      style={{ color: s.text, background: s.bg, boxShadow: `inset 0 0 0 1px ${s.ring}` }}>
      {s.icon}{type}
    </span>
  )
}

function RelevanceBar({ score }) {
  return (
    <div className="flex items-center gap-2">
      <div className="w-12 rounded-full h-1 overflow-hidden" style={{ background: 'var(--card-2)' }}>
        <div className="h-1 rounded-full" style={{ width: `${score}%`, background: 'var(--info)' }} />
      </div>
      <span className="text-xs tabular-nums" style={{ color: 'var(--text-2)' }}>{score}%</span>
    </div>
  )
}

function SuggestionCard({ suggestion }) {
  const [open, setOpen] = useState(false)
  const score = suggestion.tavily_score != null ? Math.round(suggestion.tavily_score * 100) : null

  return (
    <div className="rounded-xl p-4 mb-2.5 last:mb-0"
      style={{ background: 'var(--card-2)', boxShadow: 'inset 0 0 0 1px var(--border)' }}>
      <div className="flex items-center justify-between mb-2.5 gap-2">
        <TypeBadge type={suggestion.query_type ?? 'other'} />
        {score != null && <RelevanceBar score={score} />}
      </div>
      <a href={suggestion.source_url} target="_blank" rel="noopener noreferrer"
        className="flex items-start gap-2 group mb-2" title={suggestion.source_title}>
        <ExternalLink size={12} strokeWidth={2} className="flex-shrink-0 mt-0.5" style={{ color: 'var(--text-3)' }} />
        <span className="text-sm font-medium leading-snug line-clamp-2" style={{ color: 'var(--info)' }}>
          {suggestion.source_title ?? suggestion.source_url}
        </span>
      </a>
      {suggestion.excerpt && (
        <>
          <p className={`text-xs leading-relaxed ${open ? '' : 'line-clamp-3'}`} style={{ color: 'var(--text-2)' }}>
            {suggestion.excerpt}
          </p>
          {!open && suggestion.excerpt.length > 150 && (
            <button className="text-xs mt-1.5 font-medium" style={{ color: 'var(--text-3)' }}
              onClick={() => setOpen(true)}>
              Show more ↓
            </button>
          )}
        </>
      )}
    </div>
  )
}

function SuggestionsContent({ suggestions }) {
  if (!suggestions || suggestions.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center text-center py-8 gap-3">
        <Link2 size={28} strokeWidth={1.5} style={{ color: 'var(--text-3)' }} />
        <p className="text-sm" style={{ color: 'var(--text-2)' }}>No suggestions yet</p>
      </div>
    )
  }
  return suggestions.map((s, i) => <SuggestionCard key={i} suggestion={s} />)
}

export default function FixSuggestions({ suggestions }) {
  const [fullscreen, setFullscreen] = useState(false)

  return (
    <>
      <div className="rounded-2xl flex flex-col"
        style={{ background: 'var(--card)', boxShadow: 'inset 0 0 0 1px var(--border)' }}>

        <div className="flex items-center justify-between px-5 pt-5 pb-3">
          <h3 className="text-sm font-semibold uppercase tracking-widest" style={{ color: 'var(--text-2)' }}>
            Fix Suggestions
          </h3>
          <button onClick={() => setFullscreen(true)} style={{ color: 'var(--text-3)' }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text-2)' }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-3)' }}>
            <Maximize2 size={14} strokeWidth={2} />
          </button>
        </div>

        <div className="expand-on-print px-5 pb-5 overflow-y-auto" style={{ maxHeight: '14rem' }}>
          <SuggestionsContent suggestions={suggestions} />
        </div>
      </div>

      {fullscreen && createPortal(
        <div className="fixed inset-0 z-50 flex items-start justify-center p-6 pt-16 overflow-y-auto"
          style={{ background: 'rgba(20,23,26,0.85)', backdropFilter: 'blur(6px)' }}
          onClick={(e) => { if (e.target === e.currentTarget) setFullscreen(false) }}>
          <div className="w-full max-w-3xl rounded-2xl flex flex-col"
            style={{ background: 'var(--card)', boxShadow: '0 24px 64px rgba(0,0,0,0.5), inset 0 0 0 1px var(--border)' }}>
            <div className="flex items-center justify-between px-6 pt-6 pb-4"
              style={{ borderBottom: '1px solid var(--border)' }}>
              <h3 className="text-sm font-semibold uppercase tracking-widest" style={{ color: 'var(--text-2)' }}>
                Fix Suggestions
              </h3>
              <button onClick={() => setFullscreen(false)} style={{ color: 'var(--text-3)' }}
                onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text)' }}
                onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-3)' }}>
                <X size={16} strokeWidth={2} />
              </button>
            </div>
            <div className="px-6 py-5">
              <SuggestionsContent suggestions={suggestions} />
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  )
}
import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { Tag, Brain, Link2, Cpu } from 'lucide-react'

const STEP_LABELS = {
  classifying:    'Classifying events…',
  analyzing:      'Running RCA…',
  fetching_fixes: 'Fetching fix suggestions…',
}
const STEP_ICONS = {
  classifying:    <Tag size={13} strokeWidth={2} />,
  analyzing:      <Brain size={13} strokeWidth={2} />,
  fetching_fixes: <Link2 size={13} strokeWidth={2} />,
}

export default function RcaStream({ text, isStreaming, step, progressPct }) {
  const bottomRef = useRef(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (isStreaming && bottomRef.current) bottomRef.current.scrollIntoView({ behavior: 'smooth' })
  }, [text, isStreaming])

  async function handleCopy() {
    if (!text) return
    try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000) } catch {}
  }

  return (
    <div className="rounded-2xl overflow-hidden" style={{ background: 'var(--card)', boxShadow: 'inset 0 0 0 1px var(--border), 0 4px 24px rgba(0,0,0,0.25)' }}>
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3.5" style={{ borderBottom: '1px solid var(--border)' }}>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <div className="w-2.5 h-2.5 rounded-full" style={{ background: 'var(--error)', opacity: 0.7 }} />
            <div className="w-2.5 h-2.5 rounded-full" style={{ background: 'var(--warning)', opacity: 0.7 }} />
            <div className="w-2.5 h-2.5 rounded-full" style={{ background: 'var(--success)', opacity: 0.7 }} />
          </div>
          <span className="text-sm font-semibold uppercase tracking-widest" style={{ color: 'var(--text-2)' }}>
            Root Cause Analysis
          </span>
          {isStreaming && (
            <span className="flex items-center gap-1.5 text-xs font-medium" style={{ color: 'var(--alt)' }}>
              <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: 'var(--alt)' }} />
              Live
            </span>
          )}
        </div>

        <div className="no-print flex items-center gap-3">
          {step && (
            <span className="flex items-center gap-1.5 text-xs font-medium" style={{ color: 'var(--text-2)' }}>
              {STEP_ICONS[step] ?? <Cpu size={13} strokeWidth={2} />}
              {STEP_LABELS[step] ?? step}
            </span>
          )}
          {text && (
            <button
              onClick={handleCopy}
              className="text-xs px-2.5 py-1 rounded-lg font-medium transition-all"
              style={{ color: 'var(--text-2)', boxShadow: 'inset 0 0 0 1px var(--border)' }}
              onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text)'; e.currentTarget.style.background = 'var(--card-2)' }}
              onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-2)'; e.currentTarget.style.background = 'transparent' }}
            >
              {copied ? '✓ Copied' : 'Copy'}
            </button>
          )}
        </div>
      </div>

      {/* Progress bar */}
      {isStreaming && (
        <div className="h-0.5" style={{ background: 'var(--card-2)' }}>
          <div className="h-0.5 transition-all duration-500" style={{ width: `${progressPct ?? 0}%`, background: 'var(--info)' }} />
        </div>
      )}

      {/* Content */}
      <div className="expand-on-print px-6 py-5 max-h-[28rem] overflow-y-auto">
        {text ? (
          <div className="rca-prose"><ReactMarkdown>{text}</ReactMarkdown></div>
        ) : (
          <div className="flex flex-col items-center justify-center py-16 gap-4">
            <div className="w-14 h-14 rounded-2xl flex items-center justify-center"
              style={{ background: 'rgba(135,148,119,0.12)', boxShadow: 'inset 0 0 0 1px rgba(135,148,119,0.2)' }}>
              <Brain size={28} strokeWidth={1.5} style={{ color: 'var(--alt)' }} />
            </div>
            <div className="text-center">
              <p className="text-base font-semibold mb-1" style={{ color: 'var(--text)' }}>Waiting for analysis…</p>
              <p className="text-sm" style={{ color: 'var(--text-2)' }}>The Ultra 253B model will stream its findings here in real time.</p>
            </div>
          </div>
        )}
        {isStreaming && text && (
          <span className="inline-block w-0.5 h-4 rounded-full animate-pulse ml-0.5 align-middle" style={{ background: 'var(--info)' }} />
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
import { useState, useEffect } from 'react'
import { SearchX, ChevronRight, AlertTriangle } from 'lucide-react'
import { getSubmission, getSubmissionIncidents } from '../api'

const STATUS_STYLE = {
  pending:     { text: 'var(--text-2)',  dot: 'var(--text-3)',  bg: 'rgba(227,229,226,0.06)', ring: 'var(--border)',          pulse: false },
  classifying: { text: 'var(--info)',    dot: 'var(--info)',    bg: 'rgba(127,157,181,0.12)', ring: 'rgba(127,157,181,0.25)', pulse: true  },
  analyzing:   { text: '#A89BC0',        dot: '#A89BC0',        bg: 'rgba(168,155,192,0.12)', ring: 'rgba(168,155,192,0.25)', pulse: true  },
  complete:    { text: 'var(--success)', dot: 'var(--success)', bg: 'rgba(143,181,160,0.12)', ring: 'rgba(143,181,160,0.25)', pulse: false },
  failed:      { text: 'var(--error)',   dot: 'var(--error)',   bg: 'rgba(196,125,109,0.12)', ring: 'rgba(196,125,109,0.25)', pulse: false },
}

function StatusBadge({ status }) {
  const s = STATUS_STYLE[status] ?? STATUS_STYLE.pending
  return (
    <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold uppercase tracking-wider"
      style={{ color: s.text, background: s.bg, boxShadow: `inset 0 0 0 1px ${s.ring}` }}>
      <span className={`w-1.5 h-1.5 rounded-full ${s.pulse ? 'animate-pulse' : ''}`} style={{ backgroundColor: s.dot }} />
      {status}
    </span>
  )
}

function formatDate(iso) {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleString() } catch { return iso }
}

function ConfidenceBar({ score }) {
  const pct = Math.min(Math.round(score * 100), 99)
  const color = pct >= 80 ? 'var(--success)' : pct >= 60 ? 'var(--warning)' : 'var(--error)'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 rounded-full h-1.5 overflow-hidden" style={{ background: 'var(--card-2)' }}>
        <div className="h-1.5 rounded-full transition-all duration-500" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
      <span className="text-xs font-semibold tabular-nums" style={{ color }}>{pct}%</span>
    </div>
  )
}

export default function Dashboard({ demoStatus, onSelectIncident }) {
  const [submission, setSubmission] = useState(null)
  const [incidents, setIncidents]   = useState([])
  const [loading, setLoading]       = useState(false)
  const [error, setError]           = useState(null)

  const phase = demoStatus?.phase ?? 'idle'
  const submissionId = phase === 'idle' ? null : demoStatus?.submission_id

  useEffect(() => {
    if (!submissionId) { setSubmission(null); setIncidents([]); return }
    let cancelled = false

    async function fetchData() {
      setLoading(true); setError(null)
      try {
        const [sub, inc] = await Promise.all([getSubmission(submissionId), getSubmissionIncidents(submissionId)])
        if (!cancelled) { setSubmission(sub); setIncidents(inc?.incidents ?? []) }
      } catch (e) { if (!cancelled) setError(e.message) }
      finally { if (!cancelled) setLoading(false) }
    }

    fetchData()
    const interval = setInterval(async () => {
      try {
        const [sub, inc] = await Promise.all([getSubmission(submissionId), getSubmissionIncidents(submissionId)])
        if (!cancelled) { setSubmission(sub); setIncidents(inc?.incidents ?? []) }
      } catch {}
    }, 3000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [submissionId])

  if (!submissionId) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-6 text-center px-4">
        <div className="w-20 h-20 rounded-2xl flex items-center justify-center"
          style={{ background: 'var(--card)', boxShadow: 'inset 0 0 0 1px var(--border)' }}>
          <SearchX size={36} strokeWidth={1.5} style={{ color: 'var(--text-3)' }} />
        </div>
        <div>
          <h2 className="text-2xl font-bold mb-2" style={{ color: 'var(--text)' }}>Waiting for incident…</h2>
          <p className="text-sm max-w-sm leading-relaxed" style={{ color: 'var(--text-2)' }}>
            Click <span className="font-semibold" style={{ color: 'var(--success)' }}>Start Demo</span> in the header to begin, then{' '}
            <span className="font-semibold" style={{ color: 'var(--warning)' }}>Inject Cascade</span> to trigger an anomaly.
          </p>
        </div>
      </div>
    )
  }

  if (loading && !submission) {
    return (
      <div className="flex items-center justify-center min-h-48 gap-3" style={{ color: 'var(--text-2)' }}>
        <div className="w-5 h-5 border-2 border-current/20 border-t-current rounded-full animate-spin" />
        <span className="text-sm">Loading submission…</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="max-w-4xl mx-auto">
        <div className="rounded-xl p-4 text-sm" style={{ background: 'rgba(196,125,109,0.1)', boxShadow: 'inset 0 0 0 1px rgba(196,125,109,0.25)', color: 'var(--error)' }}>
          ⚠ Error: {error}
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold tracking-tight" style={{ color: 'var(--text)' }}>Incident Dashboard</h1>
        {submission && <StatusBadge status={submission.status} />}
      </div>

      {submission && (
        <div className="rounded-2xl p-5" style={{ background: 'var(--card)', boxShadow: 'inset 0 0 0 1px var(--border), 0 4px 24px rgba(0,0,0,0.2)' }}>
          <div className="flex items-start justify-between gap-4 mb-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-widest mb-1.5" style={{ color: 'var(--text-3)' }}>Submission ID</p>
              <p className="font-mono text-sm" style={{ color: 'var(--text)' }}>{submission.submission_id}</p>
            </div>
            <div className="text-right">
              <p className="text-xs font-semibold uppercase tracking-widest mb-1.5" style={{ color: 'var(--text-3)' }}>Created</p>
              <p className="text-sm" style={{ color: 'var(--text-2)' }}>{formatDate(submission.created_at)}</p>
            </div>
          </div>
          <div className="flex items-center gap-3 pt-4" style={{ borderTop: '1px solid var(--border)' }}>
            <span className="text-2xl font-extrabold tabular-nums" style={{ color: 'var(--info)' }}>
              {submission.incident_count ?? 0}
            </span>
            <span className="text-sm font-medium" style={{ color: 'var(--text-2)' }}>
              {(submission.incident_count ?? 0) === 1 ? 'incident' : 'incidents'} detected
            </span>
          </div>
        </div>
      )}

      <div>
        <h2 className="text-sm font-semibold uppercase tracking-widest mb-3" style={{ color: 'var(--text-2)' }}>
          Incidents ({incidents.length})
        </h2>

        {incidents.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 rounded-2xl"
            style={{ background: 'var(--card)', boxShadow: 'inset 0 0 0 1px var(--border)' }}>
            <div className="w-8 h-8 border-2 border-current/20 border-t-current rounded-full animate-spin mb-4" style={{ color: 'var(--alt)' }} />
            <p className="text-sm" style={{ color: 'var(--text-2)' }}>Analysis in progress…</p>
          </div>
        ) : (
          <div className="space-y-2.5">
            {incidents.map((inc) => (
              <button
                key={inc.incident_id}
                onClick={() => onSelectIncident({ incidentId: inc.incident_id, submissionId })}
                className="w-full text-left rounded-2xl p-4 transition-all group"
                style={{ background: 'var(--card)', boxShadow: 'inset 0 0 0 1px var(--border)' }}
                onMouseEnter={(e) => { e.currentTarget.style.boxShadow = 'inset 0 0 0 1px rgba(127,157,181,0.3), 0 4px 16px rgba(0,0,0,0.2)' }}
                onMouseLeave={(e) => { e.currentTarget.style.boxShadow = 'inset 0 0 0 1px var(--border)' }}
              >
                <div className="flex items-center justify-between mb-3">
                  <span className="font-mono text-sm" style={{ color: 'var(--text-2)' }}>
                    {inc.incident_id?.slice(0, 8)}…
                  </span>
                  <StatusBadge status={inc.status} />
                </div>
                <div className="flex items-center gap-4">
                  {inc.root_cause_service && (
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: 'var(--text-3)' }}>Root cause</span>
                      <span className="text-xs font-semibold px-2 py-0.5 rounded-full"
                        style={{ background: 'rgba(201,160,90,0.15)', color: 'var(--warning)', boxShadow: 'inset 0 0 0 1px rgba(201,160,90,0.25)' }}>
                        {inc.root_cause_service}
                      </span>
                    </div>
                  )}
                  {inc.confidence_score != null && (
                    <div className="flex-1 max-w-40"><ConfidenceBar score={inc.confidence_score} /></div>
                  )}
                  <ChevronRight size={14} strokeWidth={2} className="ml-auto" style={{ color: 'var(--text-3)' }} />
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
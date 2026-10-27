import { useState, useEffect, useRef } from 'react'
import { ArrowLeft, Download, FileDown, Lightbulb } from 'lucide-react'
import { getIncident, createSSEStream } from '../api'
import RcaStream from './RcaStream'
import CascadeChain from './CascadeChain'
import TopologyGraph from './TopologyGraph'
import FixSuggestions from './FixSuggestions'

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

function truncateId(id) {
  if (!id) return '—'
  return id.length > 16 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id
}

export default function IncidentView({ incidentId, submissionId, onBack }) {
  const [incident, setIncident] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [rcaText, setRcaText] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [step, setStep] = useState(null)
  const [progressPct, setProgressPct] = useState(0)
  const esRef = useRef(null)
  const pollRef = useRef(null)
  const streamStarted = useRef(false)

  useEffect(() => {
    if (!incidentId) return
    setLoading(true)
    setError(null)
    setRcaText('')
    setStep(null)
    setProgressPct(0)
    streamStarted.current = false

    getIncident(incidentId)
      .then((data) => {
        setIncident(data)
        setLoading(false)

        if (data.cascade_explanation) {
          setRcaText(data.cascade_explanation)
        }

        if (data.status !== 'complete' && data.status !== 'failed' && !streamStarted.current) {
          startStream(data)
        }
      })
      .catch((e) => {
        setError(e.message)
        setLoading(false)
      })

    return () => {
      if (esRef.current) {
        esRef.current.close()
        esRef.current = null
      }
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incidentId])

  function startStream(incidentData) {
    if (streamStarted.current) return
    streamStarted.current = true
    setIsStreaming(true)

    const sid = submissionId ?? incidentData?.submission_id
    if (!sid) {
      setIsStreaming(false)
      return
    }

    const es = createSSEStream(sid, {
      onToken: (token) => {
        setRcaText((prev) => prev + token)
      },
      onStep: (s, pct) => {
        setStep(s)
        setProgressPct(pct)
      },
      onComplete: () => {
        setIsStreaming(false)
        setProgressPct(100)
        // Poll every 3 s until cascade_chain and fix_suggestions are both populated.
        // fix_suggestions arrive from Tavily after the stream ends, so one fetch is never enough.
        pollRef.current = setInterval(async () => {
          try {
            const data = await getIncident(incidentId)
            setIncident(data)
            if (data.cascade_chain?.length > 0 && data.fix_suggestions?.length > 0) {
              clearInterval(pollRef.current)
              pollRef.current = null
            }
          } catch {}
        }, 3000)
        // Hard cap: stop after 60 s regardless (Tavily may return zero results)
        setTimeout(() => {
          if (pollRef.current) {
            clearInterval(pollRef.current)
            pollRef.current = null
          }
        }, 60_000)
      },
      onError: () => {
        setIsStreaming(false)
        // Fallback: if the stream closed before __DONE__ was received (e.g. job
        // already finished before we connected), start polling so cascade_chain
        // and fix_suggestions still appear without a manual browser reload.
        if (!pollRef.current) {
          pollRef.current = setInterval(async () => {
            try {
              const data = await getIncident(incidentId)
              setIncident(data)
              if (data.cascade_chain?.length > 0 && data.fix_suggestions?.length > 0) {
                clearInterval(pollRef.current)
                pollRef.current = null
              }
            } catch {}
          }, 3000)
          setTimeout(() => {
            if (pollRef.current) {
              clearInterval(pollRef.current)
              pollRef.current = null
            }
          }, 60_000)
        }
      },
    })
    esRef.current = es
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-64 gap-3" style={{ color: 'var(--text-2)' }}>
        <div className="w-5 h-5 border-2 border-current/20 border-t-current rounded-full animate-spin" />
        <span className="text-sm">Loading incident…</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="max-w-4xl mx-auto">
        <button onClick={onBack} className="flex items-center gap-1.5 text-sm mb-5 transition-colors" style={{ color: 'var(--text-2)' }}>
          ← Back
        </button>
        <div className="rounded-xl p-4 text-sm" style={{ background: 'rgba(196,125,109,0.1)', boxShadow: 'inset 0 0 0 1px rgba(196,125,109,0.25)', color: 'var(--error)' }}>
          ⚠ Error: {error}
        </div>
      </div>
    )
  }

  // Parse root_cause_service and confidence_score live from the streaming text.
  // The ANALYSIS_JSON block streams at the end of Ultra's response, so these
  // values become available before the stream finishes and the DB is written.
  const liveRootCause = (() => {
    const m = rcaText.match(/"root_cause_service"\s*:\s*"([^"]+)"/)
    return m ? m[1] : null
  })()
  const liveConfidenceRaw = (() => {
    const m = rcaText.match(/"confidence_score"\s*:\s*([\d.]+)/)
    return m ? parseFloat(m[1]) : null
  })()
  const liveConfidenceNorm = liveConfidenceRaw != null
    ? (liveConfidenceRaw > 1 ? liveConfidenceRaw / 100 : liveConfidenceRaw)
    : null

  const rootCauseService = incident?.root_cause_service ?? liveRootCause
  const rawScore = incident?.confidence_score ?? liveConfidenceNorm

  const confidence = rawScore != null
    ? Math.min(Math.round(rawScore * 100), 99)
    : null

  const confidenceColor =
    confidence == null ? 'var(--text-2)'
    : confidence >= 80 ? 'var(--success)'
    : confidence >= 60 ? 'var(--warning)'
    : 'var(--error)'

  const cascadeChain = incident?.cascade_chain ?? []
  const topology = incident?.service_topology ?? null
  const fixSuggestions = incident?.fix_suggestions ?? []
  const displayText = rcaText || incident?.cascade_explanation || ''

  function downloadReport() {
    const now = new Date().toISOString()
    const lines = [
      `# LogTrace Incident Report`,
      ``,
      `**Generated:** ${now}  `,
      `**Incident ID:** \`${incidentId}\`  `,
      `**Status:** ${incident?.status ?? '—'}  `,
      `**Root Cause:** ${rootCauseService ?? '—'}  `,
      confidence != null ? `**Confidence:** ${confidence}%` : '',
      ``,
      `---`,
      ``,
      `## Root Cause Analysis`,
      ``,
      displayText || '_Analysis not yet available._',
    ]

    if (cascadeChain.length > 0) {
      lines.push(``, `---`, ``, `## Cascade Chain`, ``)
      cascadeChain.forEach((step, i) => {
        const svc = typeof step === 'string' ? step : (step.service ?? step.name ?? JSON.stringify(step))
        lines.push(`${i + 1}. ${svc}`)
      })
    }

    if (fixSuggestions.length > 0) {
      lines.push(``, `---`, ``, `## Fix Suggestions`, ``)
      fixSuggestions.forEach((s, i) => {
        const title = s.source_title ?? s.title ?? s.suggestion ?? (typeof s === 'string' ? s : JSON.stringify(s))
        const url = s.source_url ?? s.url ?? s.link ?? null
        const excerpt = s.excerpt ?? s.snippet ?? null
        lines.push(`### ${i + 1}. ${title}`)
        if (excerpt) lines.push(``, excerpt)
        if (url) lines.push(``, `[Source](${url})`)
        lines.push(``)
      })
    }

    if (incident?.alternative_hypotheses?.length > 0) {
      lines.push(`---`, ``, `## Alternative Hypotheses`, ``)
      incident.alternative_hypotheses.forEach((h, i) => {
        const text = typeof h === 'string' ? h : (h?.hypothesis ?? JSON.stringify(h))
        const conf = h?.confidence != null ? ` (${Math.round(h.confidence > 1 ? h.confidence : h.confidence * 100)}% likely)` : ''
        lines.push(`${i + 1}. ${text}${conf}`)
        if (h?.reason) lines.push(`   *${h.reason}*`)
      })
    }

    const md = lines.filter((l) => l !== null).join('\n')
    const blob = new Blob([md], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `logtrace-incident-${incidentId?.slice(0, 8) ?? 'report'}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  function downloadPdf() {
    const prev = document.title
    document.title = `LogTrace — Incident ${incidentId?.slice(0, 8) ?? 'report'}`
    window.print()
    document.title = prev
  }

  return (
    <div className="max-w-7xl mx-auto space-y-5">
      {/* Header card */}
      <div className="rounded-2xl p-5" style={{ background: 'var(--card)', boxShadow: 'inset 0 0 0 1px var(--border), 0 4px 24px rgba(0,0,0,0.2)' }}>
        <div className="no-print flex items-center gap-3 mb-5">
          <button onClick={onBack} className="flex items-center gap-1.5 text-sm font-medium transition-colors" style={{ color: 'var(--text-2)' }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text)' }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-2)' }}>
            <ArrowLeft size={15} strokeWidth={2} />
            <span>Back</span>
          </button>
          <div className="w-px h-4" style={{ background: 'var(--border)' }} />
          <StatusBadge status={incident?.status} />
        </div>

        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest mb-2" style={{ color: 'var(--text-3)' }}>Incident</p>
            <h1 className="font-mono text-2xl font-bold leading-none" style={{ color: 'var(--text)' }}>
              {truncateId(incidentId)}
            </h1>
          </div>

          <div className="no-print flex items-center gap-4 flex-wrap">
            {incident?.status === 'complete' && (
              <>
                <button onClick={downloadReport}
                  className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all"
                  style={{ background: 'var(--card-2)', color: 'var(--text-2)', boxShadow: 'inset 0 0 0 1px var(--border)' }}
                  onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text)' }}
                  onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-2)' }}>
                  <Download size={14} strokeWidth={2} />
                  Download .md
                </button>
                <button onClick={downloadPdf}
                  className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all"
                  style={{ background: 'var(--info)', color: 'var(--bg)' }}
                  onMouseEnter={(e) => { e.currentTarget.style.opacity = '0.9' }}
                  onMouseLeave={(e) => { e.currentTarget.style.opacity = '1' }}>
                  <FileDown size={14} strokeWidth={2} />
                  Download PDF
                </button>
              </>
            )}

            <div className="text-center">
              <p className="text-xs font-semibold uppercase tracking-widest mb-1" style={{ color: 'var(--text-3)' }}>Confidence</p>
              {confidence != null ? (
                <span className="text-2xl font-extrabold tabular-nums leading-none" style={{ color: confidenceColor }}>
                  {confidence}%
                </span>
              ) : (
                <span className="text-2xl font-extrabold leading-none" style={{ color: 'var(--text-3)' }}>—</span>
              )}
            </div>

            <div>
              <p className="text-xs font-semibold uppercase tracking-widest mb-1" style={{ color: 'var(--text-3)' }}>Root Cause</p>
              {rootCauseService ? (
                <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-bold"
                  style={{ background: 'rgba(201,160,90,0.15)', color: 'var(--warning)', boxShadow: 'inset 0 0 0 1px rgba(201,160,90,0.25)' }}>
                  <span className="w-2 h-2 rounded-full" style={{ background: 'var(--warning)' }} />
                  {rootCauseService}
                </span>
              ) : (
                <span className="text-sm font-bold" style={{ color: 'var(--text-3)' }}>—</span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* RCA stream — full width */}
      <RcaStream
        text={displayText}
        isStreaming={isStreaming}
        step={step}
        progressPct={progressPct}
      />

      {/* Bottom row — three panels (click ⊞ to open full-screen) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <CascadeChain chain={cascadeChain} />
        <TopologyGraph topology={topology} />
        <FixSuggestions suggestions={fixSuggestions} />
      </div>

      {/* Alternative hypotheses */}
      {incident?.alternative_hypotheses && incident.alternative_hypotheses.length > 0 && (
        <div className="rounded-2xl p-5" style={{ background: 'var(--card)', boxShadow: 'inset 0 0 0 1px var(--border)' }}>
          <h3 className="text-sm font-semibold uppercase tracking-widest mb-4 flex items-center gap-2" style={{ color: 'var(--text-2)' }}>
            <Lightbulb size={15} strokeWidth={2} />
            Alternative Hypotheses
          </h3>
          <ul className="space-y-3">
            {incident.alternative_hypotheses.map((h, i) => {
              const text = typeof h === 'string' ? h : (h?.hypothesis ?? JSON.stringify(h))
              const conf = h?.confidence != null ? Math.round((h.confidence > 1 ? h.confidence : h.confidence * 100)) : null
              const reason = typeof h === 'object' ? h?.reason : null
              return (
                <li key={i} className="flex gap-3 text-sm">
                  <span className="flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold mt-0.5"
                    style={{ background: 'rgba(135,148,119,0.15)', color: 'var(--alt)' }}>
                    {i + 1}
                  </span>
                  <div>
                    <span className="leading-relaxed" style={{ color: 'var(--text-2)' }}>{text}</span>
                    {conf != null && (
                      <span className="ml-2 text-xs px-1.5 py-0.5 rounded-full"
                        style={{ background: 'rgba(135,148,119,0.12)', color: 'var(--alt)' }}>
                        {conf}% likely
                      </span>
                    )}
                    {reason && (
                      <p className="text-xs mt-1 leading-relaxed" style={{ color: 'var(--text-3)' }}>{reason}</p>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </div>
  )
}
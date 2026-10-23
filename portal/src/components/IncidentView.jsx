import { useState, useEffect, useRef } from 'react'
import { getIncident, createSSEStream } from '../api'
import RcaStream from './RcaStream'
import CascadeChain from './CascadeChain'
import TopologyGraph from './TopologyGraph'
import FixSuggestions from './FixSuggestions'

const STATUS_BADGE = {
  pending: 'bg-slate-700 text-slate-300',
  classifying: 'bg-blue-700 text-white animate-pulse',
  analyzing: 'bg-violet-700 text-white animate-pulse',
  complete: 'bg-green-700 text-white',
  failed: 'bg-red-700 text-white',
}

function StatusBadge({ status }) {
  return (
    <span
      className={`px-2 py-0.5 rounded text-xs font-semibold uppercase ${
        STATUS_BADGE[status] ?? STATUS_BADGE.pending
      }`}
    >
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

  // SSE streaming state
  const [rcaText, setRcaText] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [step, setStep] = useState(null)
  const [progressPct, setProgressPct] = useState(0)

  const esRef = useRef(null)
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

        // Pre-fill RCA text if already complete
        if (data.cascade_explanation) {
          setRcaText(data.cascade_explanation)
        }

        // Start SSE if not complete
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
        // Re-fetch incident for final data
        getIncident(incidentId)
          .then((data) => setIncident(data))
          .catch(() => {})
      },
      onError: () => {
        setIsStreaming(false)
      },
    })
    esRef.current = es
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-64 gap-3 text-slate-400">
        <div className="w-5 h-5 border-2 border-slate-500 border-t-violet-400 rounded-full animate-spin" />
        Loading incident…
      </div>
    )
  }

  if (error) {
    return (
      <div className="max-w-4xl mx-auto">
        <button onClick={onBack} className="text-slate-400 hover:text-white text-sm mb-4 flex items-center gap-1">
          ← Back
        </button>
        <div className="bg-red-950 border border-red-800 rounded-lg p-4 text-red-300 text-sm">
          Error: {error}
        </div>
      </div>
    )
  }

  const confidence = incident?.confidence_score != null
    ? Math.round(incident.confidence_score * 100)
    : null

  const cascadeChain = incident?.cascade_chain ?? []
  const topology = incident?.service_topology ?? null
  const fixSuggestions = incident?.fix_suggestions ?? []
  const displayText = rcaText || incident?.cascade_explanation || ''

  return (
    <div className="max-w-7xl mx-auto space-y-4">
      {/* Header row */}
      <div className="flex items-center gap-4 flex-wrap">
        <button
          onClick={onBack}
          className="text-slate-400 hover:text-white text-sm flex items-center gap-1 transition-colors"
        >
          ← Back
        </button>
        <h1 className="text-lg font-bold text-white">
          Incident{' '}
          <span className="font-mono text-slate-400 text-base">{truncateId(incidentId)}</span>
        </h1>
        <StatusBadge status={incident?.status} />
        {confidence != null && (
          <span className="text-sm text-slate-400">
            Confidence:{' '}
            <span className="text-green-400 font-semibold">{confidence}%</span>
          </span>
        )}
        {incident?.root_cause_service && (
          <span className="text-sm text-slate-400">
            Root cause:{' '}
            <span className="text-orange-400 font-semibold">{incident.root_cause_service}</span>
          </span>
        )}
      </div>

      {/* RCA stream — full width */}
      <RcaStream
        text={displayText}
        isStreaming={isStreaming}
        step={step}
        progressPct={progressPct}
      />

      {/* Bottom row — three panels */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <CascadeChain chain={cascadeChain} />
        <TopologyGraph topology={topology} />
        <FixSuggestions suggestions={fixSuggestions} />
      </div>

      {/* Alternative hypotheses */}
      {incident?.alternative_hypotheses && incident.alternative_hypotheses.length > 0 && (
        <div className="bg-slate-900 border border-slate-700 rounded-lg p-4">
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">
            Alternative Hypotheses
          </h3>
          <ul className="space-y-1">
            {incident.alternative_hypotheses.map((h, i) => (
              <li key={i} className="text-sm text-slate-400 flex gap-2">
                <span className="text-slate-600">{i + 1}.</span>
                <span>{typeof h === 'string' ? h : JSON.stringify(h)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
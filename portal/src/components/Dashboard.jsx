import { useState, useEffect } from 'react'
import { getSubmission, getSubmissionIncidents } from '../api'

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
  return id.length > 12 ? `${id.slice(0, 8)}…` : id
}

function formatDate(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

export default function Dashboard({ demoStatus, onSelectIncident }) {
  const [submission, setSubmission] = useState(null)
  const [incidents, setIncidents] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const submissionId = demoStatus?.submission_id

  useEffect(() => {
    if (!submissionId) {
      setSubmission(null)
      setIncidents([])
      return
    }

    let cancelled = false

    async function fetchData() {
      setLoading(true)
      setError(null)
      try {
        const [sub, inc] = await Promise.all([
          getSubmission(submissionId),
          getSubmissionIncidents(submissionId),
        ])
        if (!cancelled) {
          setSubmission(sub)
          setIncidents(inc?.incidents ?? [])
        }
      } catch (e) {
        if (!cancelled) setError(e.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchData()

    // Keep refreshing while not complete
    const interval = setInterval(async () => {
      try {
        const [sub, inc] = await Promise.all([
          getSubmission(submissionId),
          getSubmissionIncidents(submissionId),
        ])
        if (!cancelled) {
          setSubmission(sub)
          setIncidents(inc?.incidents ?? [])
        }
      } catch {}
    }, 3000)

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [submissionId])

  if (!submissionId) {
    return (
      <div className="flex flex-col items-center justify-center min-h-64 gap-4 text-slate-500">
        <div className="text-6xl">🔍</div>
        <h2 className="text-xl font-semibold text-slate-400">Waiting for incident...</h2>
        <p className="text-sm text-center max-w-sm">
          Click <span className="text-green-400 font-medium">Start Demo</span> in the top bar to
          begin generating synthetic microservice logs, then{' '}
          <span className="text-orange-400 font-medium">Inject Cascade</span> to trigger an
          anomaly and kick off AI analysis.
        </p>
      </div>
    )
  }

  if (loading && !submission) {
    return (
      <div className="flex items-center justify-center min-h-32 text-slate-400 gap-3">
        <div className="w-5 h-5 border-2 border-slate-500 border-t-blue-400 rounded-full animate-spin" />
        Loading submission…
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-950 border border-red-800 rounded-lg p-4 text-red-300 text-sm">
        Error: {error}
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <h1 className="text-xl font-bold text-white">Incident Dashboard</h1>

      {/* Submission card */}
      {submission && (
        <div className="bg-slate-900 border border-slate-700 rounded-lg p-5 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs text-slate-500 uppercase tracking-wide mb-1">Submission</p>
              <p className="font-mono text-sm text-slate-200">{submission.submission_id}</p>
            </div>
            <StatusBadge status={submission.status} />
          </div>
          <div className="flex gap-6 text-sm text-slate-400">
            <span>
              Created: <span className="text-slate-200">{formatDate(submission.created_at)}</span>
            </span>
            <span>
              Incidents:{' '}
              <span className="text-slate-200 font-semibold">{submission.incident_count ?? 0}</span>
            </span>
          </div>
        </div>
      )}

      {/* Incident list */}
      <div>
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wide mb-3">
          Incidents ({incidents.length})
        </h2>
        {incidents.length === 0 ? (
          <div className="text-slate-500 text-sm py-6 text-center border border-slate-800 rounded-lg">
            No incidents yet — analysis in progress…
          </div>
        ) : (
          <div className="space-y-2">
            {incidents.map((inc) => (
              <button
                key={inc.incident_id}
                onClick={() =>
                  onSelectIncident({ incidentId: inc.incident_id, submissionId })
                }
                className="w-full text-left bg-slate-900 border border-slate-700 hover:border-slate-500 rounded-lg p-4 transition-colors group"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="font-mono text-sm text-slate-300 group-hover:text-white transition-colors">
                    {truncateId(inc.incident_id)}
                  </span>
                  <StatusBadge status={inc.status} />
                </div>
                <div className="flex items-center gap-4">
                  <span className="text-xs text-slate-500">
                    Root cause:{' '}
                    <span className="text-orange-400 font-medium">
                      {inc.root_cause_service ?? '—'}
                    </span>
                  </span>
                  {inc.confidence_score != null && (
                    <div className="flex items-center gap-2 flex-1 max-w-36">
                      <span className="text-xs text-slate-500 whitespace-nowrap">
                        {Math.round(inc.confidence_score * 100)}%
                      </span>
                      <div className="flex-1 bg-slate-800 rounded-full h-1.5">
                        <div
                          className="bg-green-500 h-1.5 rounded-full transition-all"
                          style={{ width: `${Math.round(inc.confidence_score * 100)}%` }}
                        />
                      </div>
                    </div>
                  )}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
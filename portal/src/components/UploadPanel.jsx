import { useState, useRef, useCallback, useEffect } from 'react'
import { uploadLogs, getSubmission, getSubmissionIncidents, getUploadConfig } from '../api'

// ── localStorage history ─────────────────────────────────────────────────────
const HISTORY_KEY = 'logtrace_upload_history'
const HISTORY_MAX = 20
function loadHistory() { try { return JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '[]') } catch { return [] } }
function saveHistory(e) { localStorage.setItem(HISTORY_KEY, JSON.stringify(e.slice(0, HISTORY_MAX))) }
function upsertHistory(entry) {
  const entries = loadHistory()
  const idx = entries.findIndex((e) => e.id === entry.id)
  if (idx >= 0) entries[idx] = { ...entries[idx], ...entry }
  else entries.unshift(entry)
  saveHistory(entries)
}

// ── helpers ───────────────────────────────────────────────────────────────────
const STATUS_LABEL = {
  received: 'Queued', processing: 'Analyzing', classifying: 'Classifying',
  analyzing: 'Running RCA', complete: 'Complete', no_incidents: 'No incidents', failed: 'Failed',
}
const STATUS_STYLE = {
  received:     { text: 'var(--alt)',     dot: 'var(--alt)',     bg: 'rgba(135,148,119,0.12)', ring: 'rgba(135,148,119,0.25)' },
  processing:   { text: 'var(--info)',    dot: 'var(--info)',    bg: 'rgba(127,157,181,0.12)', ring: 'rgba(127,157,181,0.25)' },
  classifying:  { text: 'var(--info)',    dot: 'var(--info)',    bg: 'rgba(127,157,181,0.12)', ring: 'rgba(127,157,181,0.25)' },
  analyzing:    { text: '#A89BC0',        dot: '#A89BC0',        bg: 'rgba(168,155,192,0.12)', ring: 'rgba(168,155,192,0.25)' },
  complete:     { text: 'var(--success)', dot: 'var(--success)', bg: 'rgba(143,181,160,0.12)', ring: 'rgba(143,181,160,0.25)' },
  no_incidents: { text: 'var(--text-2)',  dot: 'var(--text-3)',  bg: 'rgba(227,229,226,0.06)', ring: 'var(--border)'          },
  failed:       { text: 'var(--error)',   dot: 'var(--error)',   bg: 'rgba(196,125,109,0.12)', ring: 'rgba(196,125,109,0.25)' },
}
function styleFor(s) { return STATUS_STYLE[s] ?? STATUS_STYLE.received }
function isTerminal(s) { return ['complete', 'no_incidents', 'failed'].includes(s) }
function isRunning(s)  { return ['received', 'processing', 'classifying', 'analyzing'].includes(s) }
function formatAge(iso) {
  if (!iso) return ''
  const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (m < 1) return 'just now'; if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}
function fmtSize(b) {
  if (b < 1024) return `${b} B`; if (b < 1048576) return `${(b/1024).toFixed(1)} KB`
  return `${(b/1048576).toFixed(1)} MB`
}

// ── sub-components ────────────────────────────────────────────────────────────
function StatusChip({ status }) {
  const s = styleFor(status)
  return (
    <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-semibold"
      style={{ color: s.text, background: s.bg, boxShadow: `inset 0 0 0 1px ${s.ring}` }}>
      <span className={`w-2 h-2 rounded-full shrink-0 ${isRunning(status) ? 'animate-pulse' : ''}`} style={{ backgroundColor: s.dot }} />
      {STATUS_LABEL[status] ?? status}
    </span>
  )
}

const STEPS = ['received', 'classifying', 'analyzing', 'complete']
const STEP_LABELS = ['Upload', 'Classify', 'RCA', 'Done']

function Pipeline({ status }) {
  if (status === 'failed') return null
  const current = status === 'processing' ? 1 : STEPS.indexOf(status)
  return (
    <div className="flex items-center gap-0">
      {STEPS.map((step, i) => {
        const done   = current >= 0 && i <= current
        const active = i === current && !isTerminal(status)
        const s = styleFor(step)
        return (
          <div key={step} className="flex items-center flex-1">
            <div className="flex flex-col items-center gap-1.5 flex-shrink-0">
              <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold transition-all duration-500 ${active ? 'animate-pulse' : ''}`}
                style={{
                  background: done ? s.bg : 'var(--card-2)',
                  color: done ? s.dot : 'var(--text-3)',
                  boxShadow: done ? `inset 0 0 0 1.5px ${s.ring}` : 'inset 0 0 0 1px var(--border)',
                }}>
                {done && !active ? '✓' : i + 1}
              </div>
              <span className="text-xs font-medium whitespace-nowrap hidden sm:block" style={{ color: done ? s.text : 'var(--text-3)' }}>
                {STEP_LABELS[i]}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <div className="h-px flex-1 mx-1 transition-all duration-700"
                style={{ backgroundColor: i < current ? 'var(--text-3)' : 'var(--border)' }} />
            )}
          </div>
        )
      })}
    </div>
  )
}

function FileChip({ file, onRemove }) {
  return (
    <div className="flex items-center gap-2.5 rounded-xl px-3.5 py-2 text-sm"
      style={{ background: 'var(--card-2)', boxShadow: 'inset 0 0 0 1px var(--border)' }}>
      <span style={{ color: 'var(--text-2)' }}>📄</span>
      <span className="font-medium truncate max-w-44" style={{ color: 'var(--text)' }}>{file.name}</span>
      <span className="tabular-nums shrink-0" style={{ color: 'var(--text-2)' }}>{fmtSize(file.size)}</span>
      <button onClick={() => onRemove(file.name)} className="shrink-0 ml-0.5 transition-colors" style={{ color: 'var(--text-3)' }}
        onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--error)' }}
        onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-3)' }}>✕</button>
    </div>
  )
}

function IncidentCard({ inc, onClick }) {
  const score = inc.confidence_score != null ? Math.min(Math.round(inc.confidence_score * 100), 99) : null
  const scoreColor = score == null ? 'var(--text-2)' : score >= 80 ? 'var(--success)' : score >= 60 ? 'var(--warning)' : 'var(--error)'
  return (
    <button onClick={onClick} className="w-full text-left rounded-2xl p-5 transition-all"
      style={{ background: 'var(--card-2)', boxShadow: 'inset 0 0 0 1px var(--border)' }}
      onMouseEnter={(e) => { e.currentTarget.style.boxShadow = 'inset 0 0 0 1px rgba(127,157,181,0.3), 0 4px 16px rgba(0,0,0,0.2)' }}
      onMouseLeave={(e) => { e.currentTarget.style.boxShadow = 'inset 0 0 0 1px var(--border)' }}>
      <div className="flex items-center justify-between">
        <span className="text-base font-semibold" style={{ color: 'var(--text)' }}>{inc.root_cause_service ?? 'Incident'}</span>
        <div className="flex items-center gap-3">
          {score != null && <span className="text-base font-bold tabular-nums" style={{ color: scoreColor }}>{score}%</span>}
          <span className="text-sm font-medium transition-colors" style={{ color: 'var(--text-2)' }}>View analysis →</span>
        </div>
      </div>
      {score != null && (
        <div className="mt-3 h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--card)' }}>
          <div className="h-full rounded-full transition-all duration-700" style={{ width: `${score}%`, backgroundColor: scoreColor }} />
        </div>
      )}
    </button>
  )
}

function HistoryRow({ entry, onOpen, onDelete }) {
  const s = styleFor(entry.status)
  return (
    <div className="flex items-center gap-4 px-5 py-4 rounded-2xl transition-all group cursor-default"
      style={{ background: 'var(--card)', boxShadow: 'inset 0 0 0 1px var(--border)' }}
      onMouseEnter={(e) => { e.currentTarget.style.boxShadow = 'inset 0 0 0 1px rgba(127,157,181,0.2)' }}
      onMouseLeave={(e) => { e.currentTarget.style.boxShadow = 'inset 0 0 0 1px var(--border)' }}>
      <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${isRunning(entry.status) ? 'animate-pulse' : ''}`} style={{ backgroundColor: s.dot }} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2.5 flex-wrap">
          <span className="font-mono text-sm" style={{ color: 'var(--text)' }}>{entry.id ? entry.id.slice(0, 8) + '…' : '—'}</span>
          <StatusChip status={entry.status} />
        </div>
        <div className="flex items-center gap-3 mt-1">
          <span className="text-sm" style={{ color: 'var(--text-2)' }}>{formatAge(entry.createdAt)}</span>
          {entry.fileCount > 0 && <span className="text-sm" style={{ color: 'var(--text-2)' }}>{entry.fileCount} file{entry.fileCount !== 1 ? 's' : ''}</span>}
          {entry.incidentCount > 0 && <span className="text-sm font-semibold" style={{ color: 'var(--success)' }}>{entry.incidentCount} incident{entry.incidentCount !== 1 ? 's' : ''}</span>}
        </div>
      </div>
      <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
        {entry.incidentCount > 0 && (
          <button onClick={() => onOpen(entry)}
            className="px-4 py-2 rounded-xl text-sm font-semibold transition-all"
            style={{ background: 'var(--info)', color: 'var(--bg)' }}>
            Open
          </button>
        )}
        <button onClick={() => onDelete(entry.id)}
          className="w-8 h-8 flex items-center justify-center rounded-xl text-sm transition-all"
          style={{ color: 'var(--text-3)' }}
          onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--error)'; e.currentTarget.style.background = 'rgba(196,125,109,0.1)' }}
          onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-3)'; e.currentTarget.style.background = 'transparent' }}>✕</button>
      </div>
    </div>
  )
}

// ── main ──────────────────────────────────────────────────────────────────────
export default function UploadPanel({ onSelectIncident }) {
  const [files, setFiles]         = useState([])
  const [dragging, setDragging]   = useState(false)
  const [uploading, setUploading] = useState(false)
  const [active, setActive]       = useState(null)
  const [polling, setPolling]     = useState(false)
  const [error, setError]         = useState(null)
  const [limits, setLimits]       = useState({ upload_max_files: 50, upload_max_file_mb: 50, upload_max_total_mb: 200 })
  const [history, setHistory]     = useState(() => loadHistory())
  const inputRef  = useRef()
  const folderRef = useRef()
  const pollRef   = useRef(null)

  useEffect(() => { getUploadConfig().then(setLimits).catch(() => {}) }, [])
  function refreshHistory() { setHistory(loadHistory()) }
  function addFiles(incoming) {
    const names = new Set(files.map((f) => f.name))
    setFiles((prev) => [...prev, ...incoming.filter((f) => !names.has(f.name))])
  }
  const onDrop = useCallback((e) => { e.preventDefault(); setDragging(false); addFiles(Array.from(e.dataTransfer.files)) }, [files])

  async function handleUpload() {
    if (!files.length) return
    setError(null)
    if (files.length > limits.upload_max_files) return setError(`Too many files — max ${limits.upload_max_files}.`)
    const oversized = files.find((f) => f.size > limits.upload_max_file_mb * 1048576)
    if (oversized) return setError(`"${oversized.name}" exceeds the ${limits.upload_max_file_mb} MB limit.`)
    const totalMB = files.reduce((s, f) => s + f.size, 0) / 1048576
    if (totalMB > limits.upload_max_total_mb) return setError(`Total ${totalMB.toFixed(0)} MB exceeds ${limits.upload_max_total_mb} MB.`)

    setUploading(true); setActive(null)
    try {
      const result = await uploadLogs(files)
      const sid = result.submission_id
      upsertHistory({ id: sid, status: result.status ?? 'received', createdAt: new Date().toISOString(), fileCount: files.length, incidentCount: 0 })
      refreshHistory()
      setActive({ id: sid, status: result.status ?? 'received', incidents: [] })
      startPolling(sid)
    } catch (e) { setError(e.message) }
    finally { setUploading(false) }
  }

  function startPolling(sid) {
    if (pollRef.current) clearTimeout(pollRef.current)
    setPolling(true); let attempts = 0
    async function tick() {
      try {
        const [statusData, incData] = await Promise.all([getSubmission(sid), getSubmissionIncidents(sid)])
        const incidents = incData.incidents ?? []
        setActive({ id: sid, status: statusData.status, incidents })
        upsertHistory({ id: sid, status: statusData.status, incidentCount: incidents.length })
        refreshHistory()
        if (isTerminal(statusData.status) || attempts > 60) { setPolling(false); return }
      } catch {}
      attempts++; pollRef.current = setTimeout(tick, 3000)
    }
    tick()
  }

  function handleReset() {
    if (pollRef.current) clearTimeout(pollRef.current)
    setFiles([]); setActive(null); setPolling(false); setError(null)
  }

  function handleHistoryOpen(entry) {
    getSubmissionIncidents(entry.id).then((data) => {
      const incidents = data?.incidents ?? []
      if (incidents.length === 1) onSelectIncident({ incidentId: incidents[0].incident_id, submissionId: entry.id })
      else if (incidents.length > 1) {
        setActive({ id: entry.id, status: entry.status, incidents })
        setFiles([]); setError(null)
        if (isRunning(entry.status)) startPolling(entry.id)
      }
    }).catch(() => {})
  }

  function handleHistoryDelete(id) { saveHistory(loadHistory().filter((e) => e.id !== id)); refreshHistory() }

  return (
    <div className="max-w-3xl mx-auto py-8 space-y-10">

      {/* Page heading */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight" style={{ color: 'var(--text)' }}>Analyze Log Files</h1>
        <p className="text-base mt-2" style={{ color: 'var(--text-2)' }}>
          Upload logs from any service or language — AI-powered root cause analysis in seconds.
        </p>
      </div>

      {/* Card */}
      <div className="rounded-3xl overflow-hidden" style={{ background: 'var(--card)', boxShadow: '0 8px 40px rgba(0,0,0,0.4), inset 0 0 0 1px var(--border)' }}>
        {!active ? (
          <div className="p-8 space-y-6">
            {/* Drop zone */}
            <div
              onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              onClick={() => inputRef.current.click()}
              className="relative rounded-2xl border-2 border-dashed p-12 text-center cursor-pointer transition-all duration-200"
              style={{
                borderColor: dragging ? 'var(--info)' : 'var(--border)',
                background: dragging ? 'rgba(127,157,181,0.05)' : 'transparent',
              }}
            >
              <input ref={inputRef} type="file" multiple accept="text/*,application/json,.log,.txt,.ndjson" className="hidden"
                onChange={(e) => { addFiles(Array.from(e.target.files)); e.target.value = '' }} />
              <input ref={folderRef} type="file" webkitdirectory="" multiple className="hidden"
                onChange={(e) => { addFiles(Array.from(e.target.files)); e.target.value = '' }} />

              <div className="w-16 h-16 rounded-2xl mx-auto mb-5 flex items-center justify-center text-3xl"
                style={{ background: dragging ? 'rgba(127,157,181,0.15)' : 'rgba(127,157,181,0.07)', boxShadow: 'inset 0 0 0 1px rgba(127,157,181,0.15)' }}>
                {dragging ? '⬇' : '📂'}
              </div>
              <p className="text-xl font-bold mb-1" style={{ color: 'var(--text)' }}>
                {dragging ? 'Drop to add files' : 'Drop files or a folder here'}
              </p>
              <p className="text-base mb-5" style={{ color: 'var(--text-2)' }}>.log · .txt · .json · .ndjson</p>

              <div className="flex items-center justify-center gap-3" onClick={(e) => e.stopPropagation()}>
                <button type="button" onClick={() => inputRef.current.click()}
                  className="px-5 py-2.5 rounded-xl text-sm font-semibold transition-all"
                  style={{ background: 'var(--card-2)', color: 'var(--text)', boxShadow: 'inset 0 0 0 1px var(--border)' }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = '#363C42' }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = 'var(--card-2)' }}>
                  Select files
                </button>
                <button type="button" onClick={() => folderRef.current.click()}
                  className="px-5 py-2.5 rounded-xl text-sm font-semibold transition-all"
                  style={{ background: 'var(--card-2)', color: 'var(--text)', boxShadow: 'inset 0 0 0 1px var(--border)' }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = '#363C42' }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = 'var(--card-2)' }}>
                  Select folder
                </button>
              </div>
              <p className="text-sm mt-5" style={{ color: 'var(--text-3)' }}>
                Up to {limits.upload_max_files} files · {limits.upload_max_file_mb} MB each · {limits.upload_max_total_mb} MB total
              </p>
            </div>

            {/* Selected files */}
            {files.length > 0 && (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-base font-semibold" style={{ color: 'var(--text)' }}>
                    {files.length} file{files.length !== 1 ? 's' : ''} selected
                  </span>
                  <button onClick={() => setFiles([])} className="text-sm transition-colors" style={{ color: 'var(--text-2)' }}
                    onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text)' }}
                    onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-2)' }}>
                    Clear all
                  </button>
                </div>
                <div className="flex flex-wrap gap-2">
                  {files.map((f) => <FileChip key={f.name} file={f} onRemove={(n) => setFiles((p) => p.filter((x) => x.name !== n))} />)}
                </div>
              </div>
            )}

            {/* Error */}
            {error && (
              <div className="flex items-start gap-3 rounded-2xl px-5 py-4"
                style={{ background: 'rgba(196,125,109,0.1)', boxShadow: 'inset 0 0 0 1px rgba(196,125,109,0.25)' }}>
                <span className="text-lg mt-0.5" style={{ color: 'var(--error)' }}>⚠</span>
                <p className="text-sm font-medium" style={{ color: 'var(--error)' }}>{error}</p>
              </div>
            )}

            {/* Analyze button */}
            <button
              onClick={handleUpload}
              disabled={files.length === 0 || uploading}
              className="w-full py-4 rounded-2xl text-base font-bold tracking-wide transition-all disabled:cursor-not-allowed"
              style={{
                background: files.length === 0 || uploading ? 'var(--card-2)' : 'var(--info)',
                color: files.length === 0 || uploading ? 'var(--text-2)' : 'var(--bg)',
                opacity: files.length === 0 || uploading ? 0.5 : 1,
              }}
            >
              {uploading ? (
                <span className="flex items-center justify-center gap-3">
                  <span className="w-5 h-5 border-2 border-current/30 border-t-current rounded-full animate-spin" />
                  Uploading…
                </span>
              ) : (
                <span className="flex items-center justify-center gap-2">
                  🔍 {files.length > 0 ? `Run Analysis on ${files.length} file${files.length !== 1 ? 's' : ''}` : 'Select files to analyze'}
                </span>
              )}
            </button>
          </div>

        ) : (
          /* Results */
          <div className="p-8 space-y-8">
            <div>
              <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                  {polling && <span className="w-4 h-4 border-2 border-current/20 border-t-current rounded-full animate-spin shrink-0" style={{ color: 'var(--info)' }} />}
                  <StatusChip status={active.status} />
                </div>
                <span className="font-mono text-sm truncate max-w-[200px]" style={{ color: 'var(--text-3)' }}>{active.id}</span>
              </div>
              <Pipeline status={active.status} />
            </div>

            {active.incidents.length > 0 ? (
              <div className="space-y-3">
                <h3 className="text-lg font-bold" style={{ color: 'var(--text)' }}>
                  {active.incidents.length} Incident{active.incidents.length !== 1 ? 's' : ''} Detected
                </h3>
                {active.incidents.map((inc) => (
                  <IncidentCard key={inc.incident_id} inc={inc}
                    onClick={() => onSelectIncident({ incidentId: inc.incident_id, submissionId: active.id })} />
                ))}
              </div>
            ) : polling ? (
              <div className="text-center py-10">
                <p className="text-base" style={{ color: 'var(--text-2)' }}>Processing logs — incidents will appear here</p>
              </div>
            ) : active.status === 'no_incidents' ? (
              <div className="text-center py-10 space-y-3">
                <div className="text-5xl">✅</div>
                <p className="text-xl font-bold" style={{ color: 'var(--text)' }}>No incidents found</p>
                <p className="text-base" style={{ color: 'var(--text-2)' }}>These logs look healthy.</p>
              </div>
            ) : active.status === 'failed' ? (
              <div className="text-center py-10 space-y-3">
                <div className="text-5xl">❌</div>
                <p className="text-xl font-bold" style={{ color: 'var(--error)' }}>Analysis failed</p>
                <p className="text-base" style={{ color: 'var(--text-2)' }}>Check the server logs for details.</p>
              </div>
            ) : null}

            <button onClick={handleReset}
              className="w-full py-3.5 rounded-2xl text-base font-semibold transition-all"
              style={{ color: 'var(--text-2)', background: 'var(--card-2)', boxShadow: 'inset 0 0 0 1px var(--border)' }}
              onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text)'; e.currentTarget.style.background = '#363C42' }}
              onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-2)'; e.currentTarget.style.background = 'var(--card-2)' }}>
              ↺ Analyze another set of files
            </button>
          </div>
        )}
      </div>

      {/* History */}
      {history.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-bold" style={{ color: 'var(--text)' }}>Recent Analyses</h2>
            <button onClick={() => { saveHistory([]); refreshHistory() }} className="text-sm transition-colors" style={{ color: 'var(--text-3)' }}
              onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text-2)' }}
              onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-3)' }}>
              Clear history
            </button>
          </div>
          <div className="space-y-2">
            {history.map((entry) => (
              <HistoryRow key={entry.id} entry={entry} onOpen={handleHistoryOpen} onDelete={handleHistoryDelete} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
import { useState, useEffect, useRef } from 'react'
import { Zap, FolderOpen } from 'lucide-react'
import DemoPanel from './components/DemoPanel'
import Dashboard from './components/Dashboard'
import IncidentView from './components/IncidentView'
import UploadPanel from './components/UploadPanel'
import LoginScreen from './components/LoginScreen'
import { getDemoStatus, getSubmissionIncidents, getStoredApiKey, setStoredApiKey, clearStoredApiKey } from './api'

export default function App() {
  const [apiKey, setApiKey] = useState(() => getStoredApiKey())
  const [tab, setTab] = useState('demo') // 'demo' | 'upload'
  const [view, setView] = useState('dashboard')
  const [selectedIncident, setSelectedIncident] = useState(null)
  const [demoStatus, setDemoStatus] = useState({
    phase: 'idle',
    events_pushed: 0,
    auto_triggered: false,
    submission_id: null,
  })
  const prevSubmissionId = useRef(null)

  // Poll demo status every 3s
  useEffect(() => {
    let cancelled = false

    async function poll() {
      try {
        const status = await getDemoStatus()
        if (!cancelled) setDemoStatus(status)
      } catch {
        // ignore poll errors silently
      }
    }

    poll()
    const id = setInterval(poll, 3000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  // Reset navigation whenever phase goes idle (catches both manual reset and background poll)
  useEffect(() => {
    if (demoStatus.phase === 'idle') {
      prevSubmissionId.current = null
      setView('dashboard')
      setSelectedIncident(null)
    }
  }, [demoStatus.phase])

  // Auto-navigate to first incident when a new submission is auto-triggered.
  // Only lock prevSubmissionId after a successful navigate — keeps retrying on each
  // 3-second poll until incidents are ready (analysis can take 30-60 s).
  useEffect(() => {
    const sid = demoStatus?.submission_id
    if (!sid) return
    if (!demoStatus.auto_triggered) return
    if (sid === prevSubmissionId.current) return

    getSubmissionIncidents(sid)
      .then((data) => {
        const incidents = data?.incidents ?? []
        if (incidents.length > 0) {
          prevSubmissionId.current = sid   // lock only once we can navigate
          setSelectedIncident({ incidentId: incidents[0].incident_id, submissionId: sid })
          setView('incident')
        }
        // if no incidents yet: leave prevSubmissionId unset so the next poll retries
      })
      .catch(() => {})
  }, [demoStatus])

  function handleSelectIncident({ incidentId, submissionId }) {
    setSelectedIncident({ incidentId, submissionId })
    setView('incident')
  }

  function handleBack() {
    setView('dashboard')
    setSelectedIncident(null)
  }

  function handleStatusChange(newStatus) {
    if (newStatus) setDemoStatus(newStatus)
  }

  if (!apiKey) {
    return (
      <LoginScreen
        onLogin={(key) => {
          setStoredApiKey(key)
          setApiKey(key)
        }}
      />
    )
  }

  return (
    <div className="min-h-screen flex flex-col" style={{ background: 'var(--bg)', color: 'var(--text)' }}>
      <div className="no-print">
        <DemoPanel
          demoStatus={demoStatus}
          onStatusChange={handleStatusChange}
          onLogout={() => {
            clearStoredApiKey()
            setApiKey('')
          }}
        />
      </div>

      {/* Tab bar */}
      {view !== 'incident' && (
        <div className="no-print px-6 flex items-center gap-1" style={{ background: 'var(--card)', borderBottom: '1px solid var(--border)' }}>
          {[
            { id: 'demo',   label: 'Live Demo',   icon: <Zap size={14} strokeWidth={2} /> },
            { id: 'upload', label: 'Upload Logs',  icon: <FolderOpen size={14} strokeWidth={2} /> },
          ].map(({ id, label, icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className="flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-all border-b-2 -mb-px"
              style={{
                color: tab === id ? 'var(--text)' : 'var(--text-2)',
                borderBottomColor: tab === id ? 'var(--info)' : 'transparent',
              }}
            >
              {icon}{label}
            </button>
          ))}
        </div>
      )}

      <main className="flex-1 p-6">
        {view === 'incident' ? (
          <IncidentView
            incidentId={selectedIncident?.incidentId}
            submissionId={selectedIncident?.submissionId}
            onBack={handleBack}
          />
        ) : tab === 'upload' ? (
          <UploadPanel onSelectIncident={handleSelectIncident} />
        ) : (
          <Dashboard demoStatus={demoStatus} onSelectIncident={handleSelectIncident} />
        )}
      </main>
    </div>
  )
}
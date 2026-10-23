import { useState, useEffect, useRef } from 'react'
import DemoPanel from './components/DemoPanel'
import Dashboard from './components/Dashboard'
import IncidentView from './components/IncidentView'
import { getDemoStatus, getSubmissionIncidents } from './api'

export default function App() {
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

  // Auto-navigate to first incident when a new submission is auto-triggered
  useEffect(() => {
    const sid = demoStatus?.submission_id
    if (!sid) return
    if (!demoStatus.auto_triggered) return
    if (sid === prevSubmissionId.current) return

    prevSubmissionId.current = sid

    getSubmissionIncidents(sid)
      .then((data) => {
        const incidents = data?.incidents ?? []
        if (incidents.length > 0) {
          setSelectedIncident({ incidentId: incidents[0].incident_id, submissionId: sid })
          setView('incident')
        }
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

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      <DemoPanel demoStatus={demoStatus} onStatusChange={handleStatusChange} />
      <main className="flex-1 p-6">
        {view === 'dashboard' ? (
          <Dashboard demoStatus={demoStatus} onSelectIncident={handleSelectIncident} />
        ) : (
          <IncidentView
            incidentId={selectedIncident?.incidentId}
            submissionId={selectedIncident?.submissionId}
            onBack={handleBack}
          />
        )}
      </main>
    </div>
  )
}
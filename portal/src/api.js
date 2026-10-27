const BASE_URL = ''

export function getStoredApiKey() {
  return localStorage.getItem('logtrace_api_key') || ''
}

export function setStoredApiKey(key) {
  localStorage.setItem('logtrace_api_key', key)
}

export function clearStoredApiKey() {
  localStorage.removeItem('logtrace_api_key')
}

async function apiFetch(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      'X-API-Key': getStoredApiKey(),
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`HTTP ${res.status}: ${text}`)
  }
  return res.json()
}

export function getUploadConfig() {
  return apiFetch('/api/v1/config')
}

export function getDemoStatus() {
  return apiFetch('/demo/status')
}

export function startDemo() {
  return apiFetch('/demo/start', {
    method: 'POST',
    body: JSON.stringify({
      services: ['payment-service', 'order-service', 'api-gateway'],
      normal_duration_seconds: 30,
    }),
  })
}

export function triggerCascade(scenario = 'pool_exhaustion') {
  return apiFetch('/demo/cascade', {
    method: 'POST',
    body: JSON.stringify({ scenario }),
  })
}

export function resetDemo() {
  return apiFetch('/demo/reset', {
    method: 'POST',
    body: JSON.stringify({ clear_redis_streams: true, clear_db_submissions: false }),
  })
}

export function getSubmission(id) {
  return apiFetch(`/api/v1/submissions/${id}`)
}

export function getSubmissionIncidents(id) {
  return apiFetch(`/api/v1/submissions/${id}/incidents`)
}

export function getIncident(id) {
  return apiFetch(`/api/v1/incidents/${id}`)
}

/**
 * Open an SSE stream for a submission.
 * Returns the EventSource instance so caller can close it.
 *
 * Messages are JSON objects:
 *   { token: "..." }          — RCA token
 *   { step: "...", progress_pct: N }  — progress update
 *   "__DONE__"                 — stream complete
 */
/**
 * Upload log files for analysis.
 * Files must be an array of File objects.
 * Returns { submission_id, status }
 */
export async function uploadLogs(files, timeWindowSeconds = 30) {
  const form = new FormData()
  for (const f of files) {
    form.append('files', f)
  }
  form.append('time_window_seconds', String(timeWindowSeconds))

  const res = await fetch('/api/v1/submissions', {
    method: 'POST',
    headers: { 'X-API-Key': getStoredApiKey() },
    body: form,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`HTTP ${res.status}: ${text}`)
  }
  return res.json()
}

export function createSSEStream(submissionId, { onToken, onStep, onComplete, onError }) {
  const url = `${BASE_URL}/api/v1/submissions/${submissionId}/stream?api_key=${getStoredApiKey()}`
  const es = new EventSource(url)

  es.onmessage = (event) => {
    const raw = event.data
    if (raw === '__DONE__') {
      onComplete && onComplete()
      es.close()
      return
    }
    try {
      const parsed = JSON.parse(raw)
      if (parsed.token !== undefined) {
        onToken && onToken(parsed.token)
      } else if (parsed.step !== undefined) {
        onStep && onStep(parsed.step, parsed.progress_pct ?? 0)
      }
    } catch {
      // plain string token fallback
      onToken && onToken(raw)
    }
  }

  es.onerror = (err) => {
    onError && onError(err)
    es.close()
  }

  return es
}
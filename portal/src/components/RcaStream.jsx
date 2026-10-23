import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'

const STEP_LABELS = {
  classifying: 'Classifying events…',
  analyzing: 'Running RCA…',
  fetching_fixes: 'Fetching fix suggestions…',
}

export default function RcaStream({ text, isStreaming, step, progressPct }) {
  const bottomRef = useRef(null)
  const [copied, setCopied] = useState(false)

  // Auto-scroll to bottom while streaming
  useEffect(() => {
    if (isStreaming && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [text, isStreaming])

  async function handleCopy() {
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {}
  }

  const stepLabel = step ? (STEP_LABELS[step] ?? step) : null

  return (
    <div className="bg-gray-950 rounded-lg border border-green-900 p-4 font-mono text-sm text-green-400">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-green-300 font-semibold text-xs uppercase tracking-wider">
          Root Cause Analysis
        </span>
        <div className="flex items-center gap-3">
          {stepLabel && (
            <span className="text-xs text-green-600">{stepLabel}</span>
          )}
          {text && (
            <button
              onClick={handleCopy}
              className="text-xs text-green-700 hover:text-green-400 transition-colors px-2 py-0.5 border border-green-900 rounded"
            >
              {copied ? 'Copied!' : 'Copy'}
            </button>
          )}
        </div>
      </div>

      {/* Progress bar */}
      {isStreaming && (
        <div className="mb-3 bg-gray-900 rounded-full h-1 overflow-hidden">
          <div
            className="bg-green-600 h-1 rounded-full transition-all duration-300"
            style={{ width: `${progressPct ?? 0}%` }}
          />
        </div>
      )}

      {/* Content */}
      <div className="max-h-80 overflow-y-auto pr-1">
        {text ? (
          <div className="prose prose-invert prose-sm prose-green max-w-none text-green-400 [&_h1]:text-green-300 [&_h2]:text-green-300 [&_h3]:text-green-300 [&_strong]:text-green-200 [&_code]:bg-gray-900 [&_code]:text-green-300 [&_a]:text-green-400">
            <ReactMarkdown>{text}</ReactMarkdown>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-green-700 text-xs py-8 justify-center">
            <span className="w-2 h-2 rounded-full bg-green-700 animate-pulse" />
            Waiting for analysis…
          </div>
        )}
        {isStreaming && text && (
          <span className="inline-block w-2 h-4 bg-green-400 animate-pulse ml-0.5 align-middle" />
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
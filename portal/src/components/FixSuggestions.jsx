import { useState } from 'react'

const QUERY_TYPE_BADGE = {
  remediation: 'bg-green-800 text-green-200',
  vulnerability: 'bg-red-800 text-red-200',
  other: 'bg-blue-800 text-blue-200',
}

function QueryTypeBadge({ type }) {
  const cls = QUERY_TYPE_BADGE[type] ?? QUERY_TYPE_BADGE.other
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-semibold uppercase ${cls}`}>{type}</span>
  )
}

function SuggestionCard({ suggestion }) {
  const [expanded, setExpanded] = useState(false)
  const score = suggestion.tavily_score != null ? Math.round(suggestion.tavily_score * 100) : null

  return (
    <div className="bg-slate-900 border border-slate-700 rounded p-3 mb-2 last:mb-0">
      <div className="flex items-center justify-between mb-1.5 gap-2">
        <QueryTypeBadge type={suggestion.query_type ?? 'other'} />
        {score != null && (
          <span className="text-xs text-slate-400 ml-auto">{score}%</span>
        )}
      </div>

      <a
        href={suggestion.source_url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-blue-400 hover:text-blue-300 hover:underline text-sm font-medium line-clamp-2 block mb-1.5"
        title={suggestion.source_title}
      >
        {suggestion.source_title ?? suggestion.source_url}
      </a>

      {suggestion.excerpt && (
        <>
          <p
            className={`text-slate-400 text-xs cursor-pointer ${
              expanded ? '' : 'line-clamp-3'
            }`}
            onClick={() => setExpanded((e) => !e)}
            title={expanded ? 'Click to collapse' : 'Click to expand'}
          >
            {suggestion.excerpt}
          </p>
          {!expanded && suggestion.excerpt.length > 150 && (
            <button
              className="text-slate-600 hover:text-slate-400 text-xs mt-0.5"
              onClick={() => setExpanded(true)}
            >
              Show more
            </button>
          )}
        </>
      )}
    </div>
  )
}

export default function FixSuggestions({ suggestions }) {
  return (
    <div className="bg-slate-900 rounded-lg border border-slate-700 p-4 h-full flex flex-col">
      <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">
        Fix Suggestions
      </h3>

      {!suggestions || suggestions.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-slate-600 text-sm text-center py-8">
          No suggestions yet
        </div>
      ) : (
        <div className="overflow-y-auto flex-1">
          {suggestions.map((s, i) => (
            <SuggestionCard key={i} suggestion={s} />
          ))}
        </div>
      )}
    </div>
  )
}
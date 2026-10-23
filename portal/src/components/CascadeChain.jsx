const STEP_COLORS = ['bg-red-600', 'bg-orange-500', 'bg-yellow-500']

function getStepColor(index) {
  return STEP_COLORS[index] ?? 'bg-yellow-500'
}

function formatTimestamp(ts) {
  if (!ts) return '—'
  try {
    const d = new Date(ts)
    const hh = String(d.getUTCHours()).padStart(2, '0')
    const mm = String(d.getUTCMinutes()).padStart(2, '0')
    const ss = String(d.getUTCSeconds()).padStart(2, '0')
    return `${hh}:${mm}:${ss} UTC`
  } catch {
    return ts
  }
}

export default function CascadeChain({ chain }) {
  return (
    <div className="bg-slate-900 rounded-lg border border-slate-700 p-4 h-full">
      <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-4">
        Cascade Chain
      </h3>

      {!chain || chain.length === 0 ? (
        <div className="text-slate-600 text-sm text-center py-8">No cascade data yet</div>
      ) : (
        <div className="relative space-y-0">
          {chain.map((item, idx) => (
            <div key={idx} className="relative flex gap-3">
              {/* Vertical connector line */}
              {idx < chain.length - 1 && (
                <div className="absolute left-4 top-8 bottom-0 w-0.5 bg-slate-700" />
              )}

              {/* Step circle */}
              <div className="flex-shrink-0 z-10">
                <div
                  className={`w-8 h-8 rounded-full ${getStepColor(idx)} flex items-center justify-center text-white text-xs font-bold`}
                >
                  {idx + 1}
                </div>
              </div>

              {/* Content */}
              <div className="pb-6 min-w-0 flex-1">
                {/* Service badge */}
                <span className="inline-block bg-slate-800 border border-slate-600 text-slate-200 text-xs px-2 py-0.5 rounded font-mono mb-1">
                  {item.service ?? '—'}
                </span>

                {/* Error message */}
                {item.error && (
                  <p className="text-xs text-red-400 truncate mt-0.5" title={item.error}>
                    {item.error}
                  </p>
                )}

                {/* Timestamp */}
                <p className="text-xs text-slate-600 mt-0.5">
                  {formatTimestamp(item.timestamp)}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
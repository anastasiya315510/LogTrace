import { useState } from 'react'
import { Maximize2, X } from 'lucide-react'
import { createPortal } from 'react-dom'

const ROLE_META = {
  root_cause:       { color: '#C47D6D', fill: 'rgba(196,125,109,0.15)', border: 'rgba(196,125,109,0.5)', label: 'Root Cause'  },
  propagated_error: { color: '#C9A05A', fill: 'rgba(201,160,90,0.12)',  border: 'rgba(201,160,90,0.4)',  label: 'Propagated'  },
  symptom:          { color: '#7F9DB5', fill: 'rgba(127,157,181,0.12)', border: 'rgba(127,157,181,0.4)', label: 'Symptom'     },
  unknown:          { color: '#879477', fill: 'rgba(135,148,119,0.12)', border: 'rgba(135,148,119,0.35)', label: 'Unknown'    },
}

const ROLE_ORDER = ['root_cause', 'propagated_error', 'symptom', 'unknown']

function NodeCard({ node, role, count, isRoot }) {
  const meta = ROLE_META[role] ?? ROLE_META.unknown
  return (
    <div
      className="flex items-center gap-2.5 px-3.5 py-2.5 rounded-xl w-full"
      style={{
        background: meta.fill,
        boxShadow: isRoot
          ? `inset 0 0 0 1.5px ${meta.border}, 0 0 12px ${meta.fill}`
          : `inset 0 0 0 1px ${meta.border}`,
      }}
    >
      <div className="flex-shrink-0 w-2 h-2 rounded-full"
        style={{ background: meta.color, ...(isRoot ? { boxShadow: `0 0 6px ${meta.color}` } : {}) }} />
      <div className="min-w-0 flex-1">
        <p className="text-xs font-semibold leading-tight truncate"
          style={{ color: meta.color, fontFamily: "'JetBrains Mono', 'Fira Code', ui-monospace, monospace" }}
          title={node}>
          {node}
        </p>
        {count != null && (
          <p className="text-xs leading-none mt-0.5" style={{ color: meta.color, opacity: 0.6 }}>
            {count} error{count !== 1 ? 's' : ''}
          </p>
        )}
      </div>
    </div>
  )
}

function FlowArrow() {
  return (
    <div className="flex flex-col items-center py-0.5 flex-shrink-0">
      <div className="w-px h-3" style={{ background: 'rgba(227,229,226,0.12)' }} />
      <div style={{
        width: 0, height: 0,
        borderLeft: '4px solid transparent',
        borderRight: '4px solid transparent',
        borderTop: '5px solid rgba(227,229,226,0.15)',
      }} />
    </div>
  )
}

function TopologyContent({ topology }) {
  if (!topology || !topology.node_roles || Object.keys(topology.node_roles).length === 0) {
    return (
      <div className="flex items-center justify-center py-8">
        <p className="text-sm" style={{ color: 'var(--text-2)' }}>No topology data yet</p>
      </div>
    )
  }

  const { node_roles, error_counts } = topology

  const layers = ROLE_ORDER.reduce((acc, role) => {
    const nodes = Object.entries(node_roles)
      .filter(([, r]) => r === role)
      .map(([n]) => n)
    if (nodes.length > 0) acc.push({ role, nodes })
    return acc
  }, [])

  const unknownExtra = Object.entries(node_roles)
    .filter(([, r]) => !ROLE_META[r])
    .map(([n]) => n)
  if (unknownExtra.length > 0) {
    const existing = layers.find(l => l.role === 'unknown')
    if (existing) existing.nodes.push(...unknownExtra)
    else layers.push({ role: 'unknown', nodes: unknownExtra })
  }

  return (
    <div className="flex flex-col">
      {layers.map((layer, li) => {
        const meta = ROLE_META[layer.role] ?? ROLE_META.unknown
        return (
          <div key={layer.role}>
            {li > 0 && <FlowArrow />}
            <p className="text-center mb-1.5"
              style={{ fontSize: '9px', fontWeight: 700, letterSpacing: '0.1em', color: meta.color, opacity: 0.55 }}>
              {meta.label.toUpperCase()}
            </p>
            <div className="flex flex-col gap-1.5">
              {layer.nodes.map((node) => (
                <NodeCard
                  key={node}
                  node={node}
                  role={layer.role}
                  count={error_counts?.[node] ?? null}
                  isRoot={layer.role === 'root_cause'}
                />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default function TopologyGraph({ topology }) {
  const [fullscreen, setFullscreen] = useState(false)

  return (
    <>
      <div className="rounded-2xl flex flex-col"
        style={{ background: 'var(--card)', boxShadow: 'inset 0 0 0 1px var(--border)' }}>

        <div className="flex items-center justify-between px-5 pt-5 pb-3">
          <h3 className="text-sm font-semibold uppercase tracking-widest" style={{ color: 'var(--text-2)' }}>
            Service Topology
          </h3>
          <button onClick={() => setFullscreen(true)} style={{ color: 'var(--text-3)' }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text-2)' }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-3)' }}>
            <Maximize2 size={14} strokeWidth={2} />
          </button>
        </div>

        <div className="expand-on-print px-5 pb-5 overflow-y-auto" style={{ maxHeight: '14rem' }}>
          <TopologyContent topology={topology} />
        </div>
      </div>

      {fullscreen && createPortal(
        <div className="fixed inset-0 z-50 flex items-start justify-center p-6 pt-16 overflow-y-auto"
          style={{ background: 'rgba(20,23,26,0.85)', backdropFilter: 'blur(6px)' }}
          onClick={(e) => { if (e.target === e.currentTarget) setFullscreen(false) }}>
          <div className="w-full max-w-xl rounded-2xl flex flex-col"
            style={{ background: 'var(--card)', boxShadow: '0 24px 64px rgba(0,0,0,0.5), inset 0 0 0 1px var(--border)' }}>
            <div className="flex items-center justify-between px-6 pt-6 pb-4"
              style={{ borderBottom: '1px solid var(--border)' }}>
              <h3 className="text-sm font-semibold uppercase tracking-widest" style={{ color: 'var(--text-2)' }}>
                Service Topology
              </h3>
              <button onClick={() => setFullscreen(false)} style={{ color: 'var(--text-3)' }}
                onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text)' }}
                onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-3)' }}>
                <X size={16} strokeWidth={2} />
              </button>
            </div>
            <div className="px-6 py-5">
              <TopologyContent topology={topology} />
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  )
}
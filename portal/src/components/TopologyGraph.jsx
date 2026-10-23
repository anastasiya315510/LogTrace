const ROLE_COLORS = {
  root_cause: '#ef4444',
  propagated_error: '#f97316',
  symptom: '#eab308',
  unknown: '#64748b',
}

function getNodeColor(role) {
  return ROLE_COLORS[role] ?? ROLE_COLORS.unknown
}

function shortName(name) {
  if (!name) return '?'
  // Truncate long service names for display
  return name.length > 12 ? name.slice(0, 11) + '…' : name
}

export default function TopologyGraph({ topology }) {
  if (!topology || !topology.node_roles || Object.keys(topology.node_roles).length === 0) {
    return (
      <div className="bg-slate-950 rounded-lg border border-slate-700 p-4 flex items-center justify-center">
        <p className="text-slate-600 text-sm">No topology data yet</p>
      </div>
    )
  }

  const { node_roles, adjacency, error_counts, edge_weights } = topology

  // Group nodes by role for layout
  const roleGroups = {}
  for (const [node, role] of Object.entries(node_roles)) {
    if (!roleGroups[role]) roleGroups[role] = []
    roleGroups[role].push(node)
  }

  const roleOrder = ['root_cause', 'propagated_error', 'symptom', 'unknown']
  const xPositions = { root_cause: 80, propagated_error: 200, symptom: 320, unknown: 440 }

  const nodePositions = {}
  for (const role of roleOrder) {
    const nodes = roleGroups[role] ?? []
    nodes.forEach((node, i) => {
      const baseY = nodes.length === 1 ? 110 : 70 + i * 60
      nodePositions[node] = {
        x: xPositions[role] ?? 80,
        y: baseY,
      }
    })
  }

  const svgHeight = 220
  const svgWidth = 520

  // Build edges
  const edges = []
  if (adjacency) {
    for (const [src, targets] of Object.entries(adjacency)) {
      for (const tgt of targets) {
        if (nodePositions[src] && nodePositions[tgt]) {
          const weight = edge_weights?.[`${src}->${tgt}`] ?? edge_weights?.[src]?.[tgt] ?? null
          edges.push({ src, tgt, weight })
        }
      }
    }
  }

  const nodes = Object.keys(nodePositions)

  return (
    <div className="bg-slate-950 rounded-lg border border-slate-700 p-4">
      <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">
        Service Topology
      </h3>
      <svg
        width="100%"
        viewBox={`0 0 ${svgWidth} ${svgHeight}`}
        className="w-full"
        style={{ height: '200px' }}
      >
        <defs>
          <marker
            id="arrowhead"
            markerWidth="6"
            markerHeight="4"
            refX="6"
            refY="2"
            orient="auto"
          >
            <polygon points="0 0, 6 2, 0 4" fill="#475569" />
          </marker>
        </defs>

        {/* Edges */}
        {edges.map(({ src, tgt, weight }, i) => {
          const s = nodePositions[src]
          const t = nodePositions[tgt]
          const dx = t.x - s.x
          const dy = t.y - s.y
          const len = Math.sqrt(dx * dx + dy * dy)
          const r = 28
          const sx = s.x + (dx / len) * r
          const sy = s.y + (dy / len) * r
          const ex = t.x - (dx / len) * (r + 6)
          const ey = t.y - (dy / len) * (r + 6)
          const mx = (sx + ex) / 2
          const my = (sy + ey) / 2

          return (
            <g key={i}>
              <line
                x1={sx}
                y1={sy}
                x2={ex}
                y2={ey}
                stroke="#475569"
                strokeWidth="1.5"
                markerEnd="url(#arrowhead)"
              />
              {weight != null && (
                <text x={mx} y={my - 4} fill="#64748b" fontSize="9" textAnchor="middle">
                  {weight}
                </text>
              )}
            </g>
          )
        })}

        {/* Nodes */}
        {nodes.map((node) => {
          const { x, y } = nodePositions[node]
          const role = node_roles[node] ?? 'unknown'
          const color = getNodeColor(role)
          const count = error_counts?.[node] ?? null

          return (
            <g key={node}>
              <circle cx={x} cy={y} r={28} fill={color} opacity={0.85} />
              {count != null && (
                <text
                  x={x}
                  y={y + 4}
                  fill="white"
                  fontSize="11"
                  fontWeight="bold"
                  textAnchor="middle"
                >
                  {count}
                </text>
              )}
              <text
                x={x}
                y={y + 38}
                fill="#94a3b8"
                fontSize="9"
                textAnchor="middle"
              >
                {shortName(node)}
              </text>
            </g>
          )
        })}
      </svg>

      {/* Legend */}
      <div className="flex flex-wrap gap-2 mt-2">
        {Object.entries(ROLE_COLORS).map(([role, color]) => (
          <div key={role} className="flex items-center gap-1">
            <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
            <span className="text-slate-500 text-xs">{role.replace('_', ' ')}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
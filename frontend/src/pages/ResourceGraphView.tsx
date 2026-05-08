import { useMemo, useRef, useState, useEffect } from 'react'
import ForceGraph2D, { type LinkObject, type NodeObject } from 'react-force-graph-2d'

import { Card } from '@/components/ui/card'
import * as api from '@/lib/api'
import type { ResourceGraph } from '@/types/api'
import { useCachedFetch } from '@/lib/cache'

interface Props {
  days: number
}

type Kind = 'space' | 'resource'

interface GraphNode extends NodeObject {
  id: string
  kind: Kind
  label: string
  query_count: number
}

interface GraphLink extends LinkObject {
  source: string | GraphNode
  target: string | GraphNode
  query_count: number
}

const SPACE_COLOR = '#FF3621'      // Databricks red
const RESOURCE_COLOR = '#1B3139'   // Databricks navy
const HIGHLIGHT_COLOR = '#FFAB00'  // amber

export function ResourceGraphView({ days }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 800, height: 640 })

  const { data, error: err } = useCachedFetch<ResourceGraph>(
    `graph:${days}:2000`,
    () => api.getResourceGraph(days, 2000),
    [days],
  )

  const allSpaceIds = useMemo(() => data?.spaces.map(s => s.space_id) ?? [], [data])
  const titleBySpace = useMemo(
    () => Object.fromEntries((data?.spaces ?? []).map(s => [s.space_id, s.title ?? s.space_id])),
    [data],
  )
  const [selectedSpaceIds, setSelectedSpaceIds] = useState<Set<string> | null>(null)

  // Reset selection when underlying space list changes (e.g. days window).
  useEffect(() => {
    setSelectedSpaceIds(null)
  }, [data])

  const activeSpaces = useMemo<Set<string>>(
    () => selectedSpaceIds ?? new Set(allSpaceIds),
    [selectedSpaceIds, allSpaceIds],
  )

  // Resize observer so the graph fills its container.
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => {
      const cr = entry.contentRect
      setSize({ width: Math.max(400, cr.width), height: Math.max(400, cr.height) })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const graph = useMemo(() => {
    if (!data) return { nodes: [] as GraphNode[], links: [] as GraphLink[] }
    const nodes: Record<string, GraphNode> = {}
    const links: GraphLink[] = []
    for (const e of data.edges) {
      if (!activeSpaces.has(e.space_id)) continue
      const sId = `space:${e.space_id}`
      const rId = `resource:${e.full_name}`
      if (!nodes[sId]) {
        nodes[sId] = {
          id: sId, kind: 'space',
          label: titleBySpace[e.space_id] ?? e.space_id,
          query_count: 0,
        }
      }
      if (!nodes[rId]) {
        nodes[rId] = { id: rId, kind: 'resource', label: e.full_name, query_count: 0 }
      }
      nodes[sId].query_count += e.query_count
      nodes[rId].query_count += e.query_count
      links.push({ source: sId, target: rId, query_count: e.query_count })
    }
    return { nodes: Object.values(nodes), links }
  }, [data, activeSpaces, titleBySpace])

  const [hoverId, setHoverId] = useState<string | null>(null)
  const neighborhood = useMemo(() => {
    if (!hoverId) return null
    const adj = new Set<string>([hoverId])
    for (const l of graph.links) {
      const s = typeof l.source === 'string' ? l.source : l.source.id
      const t = typeof l.target === 'string' ? l.target : l.target.id
      if (s === hoverId) adj.add(t)
      if (t === hoverId) adj.add(s)
    }
    return adj
  }, [hoverId, graph.links])

  const filterCount = useMemo(() => {
    if (!data) return { selected: 0, total: 0 }
    return { selected: activeSpaces.size, total: allSpaceIds.length }
  }, [activeSpaces, allSpaceIds, data])

  return (
    <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
      <Card className="flex flex-col p-0">
        <div className="border-b border-default px-4 py-3 text-xs uppercase text-muted">
          Genie Space filter
          <div className="mt-1 normal-case text-[10px] text-muted/80">
            {filterCount.selected} / {filterCount.total} selected
          </div>
        </div>
        <div className="flex gap-2 border-b border-default px-3 py-2 text-xs">
          <button
            className="rounded border border-default px-2 py-1 hover:bg-elevated"
            onClick={() => setSelectedSpaceIds(null)}
          >
            All
          </button>
          <button
            className="rounded border border-default px-2 py-1 hover:bg-elevated"
            onClick={() => setSelectedSpaceIds(new Set())}
          >
            None
          </button>
        </div>
        <div className="max-h-[560px] overflow-y-auto p-2">
          {data?.spaces.map(s => {
            const checked = activeSpaces.has(s.space_id)
            return (
              <label
                key={s.space_id}
                className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-xs hover:bg-elevated/50"
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => {
                    const next = new Set(activeSpaces)
                    if (checked) next.delete(s.space_id)
                    else next.add(s.space_id)
                    setSelectedSpaceIds(next)
                  }}
                />
                <span className="truncate" title={s.space_id}>
                  {s.title ?? s.space_id}
                </span>
              </label>
            )
          })}
          {!data && <div className="p-4 text-center text-xs text-muted">Loading…</div>}
          {data && !data.spaces.length && (
            <div className="p-4 text-center text-xs text-muted">No spaces with lineage events.</div>
          )}
        </div>
      </Card>

      <Card className="overflow-hidden p-0">
        <div className="flex items-center justify-between border-b border-default px-4 py-2 text-xs uppercase text-muted">
          <span>Bipartite graph — {graph.nodes.length} nodes · {graph.links.length} edges</span>
          {data?.truncated && (
            <span className="normal-case text-amber-500">
              edges truncated — showing top 2,000
            </span>
          )}
        </div>
        {err && <div className="p-3 text-sm text-red-400">{err}</div>}
        <div ref={containerRef} className="h-[640px] w-full">
          {data ? (
            <ForceGraph2D
              graphData={graph}
              width={size.width}
              height={size.height}
              backgroundColor="transparent"
              nodeRelSize={5}
              nodeVal={(n: NodeObject) => Math.max(2, Math.log2(((n as GraphNode).query_count || 1) + 1))}
              nodeColor={(n: NodeObject) => {
                const node = n as GraphNode
                if (neighborhood && !neighborhood.has(node.id)) return '#94a3b855'
                return node.kind === 'space' ? SPACE_COLOR : RESOURCE_COLOR
              }}
              nodeLabel={(n: NodeObject) => {
                const node = n as GraphNode
                const kindLabel = node.kind === 'space' ? 'Genie Space' : 'Resource'
                return `<div style="font:12px sans-serif"><b>${kindLabel}</b><br>${node.label}<br><span style="opacity:.7">${node.query_count} queries</span></div>`
              }}
              linkColor={(l: LinkObject) => {
                if (!neighborhood) return '#cbd5e155'
                const link = l as GraphLink
                const s = typeof link.source === 'string' ? link.source : link.source.id
                const t = typeof link.target === 'string' ? link.target : link.target.id
                return neighborhood.has(s) && neighborhood.has(t) ? HIGHLIGHT_COLOR : '#cbd5e122'
              }}
              linkWidth={(l: LinkObject) => Math.min(4, Math.log2(((l as GraphLink).query_count || 1) + 1))}
              onNodeHover={(n: NodeObject | null) => setHoverId(n ? (n as GraphNode).id : null)}
              cooldownTicks={120}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-xs text-muted">
              Loading lineage graph…
            </div>
          )}
        </div>
        <div className="flex items-center gap-4 border-t border-default px-4 py-2 text-xs text-muted">
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: SPACE_COLOR }} />
            Genie Space
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: RESOURCE_COLOR }} />
            Resource (table / view)
          </span>
          <span className="ml-auto">Hover a node to highlight its neighborhood.</span>
        </div>
      </Card>
    </div>
  )
}

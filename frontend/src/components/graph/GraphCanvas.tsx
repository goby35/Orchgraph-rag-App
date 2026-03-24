"use client"

import dagre from "@dagrejs/dagre"
import { type MouseEvent, useCallback, useEffect, useMemo } from "react"
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
} from "reactflow"

import "reactflow/dist/style.css"

import type { OrgNodeData, PersonnelNodeData } from "@/types"

import OrgNode from "./OrgNode"
import PersonnelNode from "./PersonnelNode"

const nodeTypes = {
  personnel: PersonnelNode,
  org: OrgNode,
}

function applyDagreLayout(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: "LR", nodesep: 60, ranksep: 100 })

  nodes.forEach((n) => {
    const w = n.type === "org" ? 120 : 80
    const h = n.type === "org" ? 52 : 80
    g.setNode(n.id, { width: w, height: h })
  })
  edges.forEach((e) => {
    g.setEdge(e.source, e.target)
  })
  dagre.layout(g)

  return nodes.map((n) => {
    const pos = g.node(n.id) as { x: number; y: number } | undefined
    const w = n.type === "org" ? 120 : 80
    const h = n.type === "org" ? 52 : 80
    if (!pos) return { ...n, position: { x: 0, y: 0 } }
    return {
      ...n,
      position: { x: pos.x - w / 2, y: pos.y - h / 2 },
    }
  })
}

function buildAcceptedPersonnelSet(edgesRaw: unknown[]): Set<string> {
  const set = new Set<string>()
  for (const e of edgesRaw) {
    if (!e || typeof e !== "object") continue
    const edge = e as Record<string, unknown>
    if (String(edge.label) === "accepted" && edge.target != null) {
      set.add(String(edge.target))
    }
  }
  return set
}

/** Khớp GET /graph (Neo4j → JSON `nodes` / `edges`). */
export function transformGraphData(raw: unknown): {
  nodes: Node[]
  edges: Edge[]
} {
  if (!raw || typeof raw !== "object") return { nodes: [], edges: [] }
  const data = raw as Record<string, unknown>
  const nodesRaw = (data.nodes as unknown[]) ?? []
  const edgesRaw = (data.edges as unknown[]) ?? []

  const accepted = buildAcceptedPersonnelSet(edgesRaw)

  const rfNodes: Node[] = nodesRaw.map((n) => {
    const node = n as Record<string, unknown>
    const id = String(node.id ?? "")
    const nType = String(node.type ?? "")
    const inner = (node.data as Record<string, unknown>) ?? {}
    const label = String(inner.label ?? id)

    if (nType === "org") {
      const nodeData: OrgNodeData = {
        id,
        label,
        industry:
          typeof inner.industry === "string" ? inner.industry : undefined,
      }
      return {
        id,
        type: "org",
        position: { x: 0, y: 0 },
        data: nodeData,
      }
    }

    const nodeData: PersonnelNodeData = {
      id,
      label,
      availability: accepted.has(id),
      summary: undefined,
      skills: undefined,
    }
    return {
      id,
      type: "personnel",
      position: { x: 0, y: 0 },
      data: nodeData,
    }
  })

  const rfEdges: Edge[] = edgesRaw.map((e, i) => {
    const edge = e as Record<string, unknown>
    const stroke =
      edge.style &&
      typeof edge.style === "object" &&
      edge.style !== null &&
      "stroke" in edge.style
        ? String((edge.style as { stroke?: string }).stroke ?? "#94a3b8")
        : "#94a3b8"
    return {
      id: String(edge.id ?? `e-${i}`),
      source: String(edge.source ?? ""),
      target: String(edge.target ?? ""),
      label: String(edge.label ?? ""),
      type: "smoothstep",
      style: { stroke },
    }
  })

  const laidOut = applyDagreLayout(rfNodes, rfEdges)
  return { nodes: laidOut, edges: rfEdges }
}

export interface GraphNodeSelection {
  id: string
  type: "personnel" | "org"
  data: PersonnelNodeData | OrgNodeData
}

interface GraphCanvasProps {
  data: unknown
  onNodeClick?: (sel: GraphNodeSelection) => void
}

export default function GraphCanvas({ data, onNodeClick }: GraphCanvasProps) {
  const transformed = useMemo(() => transformGraphData(data), [data])
  const [nodes, setNodes, onNodesChange] = useNodesState(transformed.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(transformed.edges)

  useEffect(() => {
    setNodes(transformed.nodes)
    setEdges(transformed.edges)
  }, [transformed.nodes, transformed.edges, setNodes, setEdges])

  const handleNodeClick = useCallback(
    (_: MouseEvent, node: Node) => {
      const t = node.type
      if (t !== "personnel" && t !== "org") return
      const d = node.data as PersonnelNodeData | OrgNodeData
      onNodeClick?.({ id: node.id, type: t, data: d })
    },
    [onNodeClick],
  )

  return (
    <div className="border-input h-[min(70vh,600px)] w-full overflow-hidden rounded-lg border">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        fitView
        attributionPosition="bottom-right"
      >
        <Background />
        <Controls />
        <MiniMap
          nodeColor={(n) => (n.type === "org" ? "#93c5fd" : "#86efac")}
          maskColor="rgb(0 0 0 / 12%)"
        />
      </ReactFlow>
    </div>
  )
}

"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import dynamic from "next/dynamic"

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
})

type GraphNodeType = "personnel" | "org" | "skill" | string

export interface GraphNodeData {
  label: string
  type: GraphNodeType
  summary?: string
  skills?: string[]
  availability?: boolean
  industry?: string
  [key: string]: unknown
}

export interface GraphNode {
  id: string
  label: string
  type: GraphNodeType
  data: GraphNodeData
  x?: number
  y?: number
  vx?: number
  vy?: number
}

export interface GraphLink {
  id: string
  source: string | GraphNode
  target: string | GraphNode
  label?: string
}

export interface GraphData {
  nodes: GraphNode[]
  links: GraphLink[]
}

export type GraphNodeSelection = GraphNode

function buildAcceptedPersonnelSet(edgesRaw: unknown[]): Set<string> {
  const set = new Set<string>()
  for (const edgeRaw of edgesRaw) {
    if (!edgeRaw || typeof edgeRaw !== "object") continue
    const edge = edgeRaw as Record<string, unknown>
    if (String(edge.label) === "accepted" && edge.target != null) {
      set.add(String(edge.target))
    }
  }
  return set
}

export function transformGraphData(raw: unknown): GraphData {
  if (!raw || typeof raw !== "object") return { nodes: [], links: [] }

  const data = raw as Record<string, unknown>
  const nodesRaw = Array.isArray(data.nodes) ? data.nodes : []
  const edgesRaw = Array.isArray(data.edges)
    ? data.edges
    : Array.isArray(data.links)
      ? data.links
      : []

  const accepted = buildAcceptedPersonnelSet(edgesRaw)

  const nodes: GraphNode[] = nodesRaw.map((rawNode) => {
    const node = rawNode as Record<string, unknown>
    const id = String(node.id ?? "")
    const nodeType = String(node.type ?? "") as GraphNodeType
    const inner = (node.data as Record<string, unknown>) ?? {}
    const personnelFullName =
      typeof inner.public_full_name === "string"
        ? inner.public_full_name
        : typeof inner.full_name === "string"
          ? inner.full_name
          : undefined
    const label = String(
      nodeType === "personnel"
        ? personnelFullName ?? inner.label ?? node.label ?? id
        : inner.label ?? node.label ?? id,
    )
    const summary =
      typeof inner.summary === "string"
        ? inner.summary
        : typeof inner.professional_summary === "string"
          ? inner.professional_summary
          : typeof inner.public_professional_summary === "string"
            ? inner.public_professional_summary
            : undefined
    const skills = Array.isArray(inner.skills)
      ? inner.skills.map(String)
      : []

    return {
      id,
      label,
      type: nodeType,
      data: {
        label,
        type: nodeType,
        public_full_name:
          personnelFullName,
        summary,
        skills,
        availability: accepted.has(id),
        industry:
          typeof inner.industry === "string" ? inner.industry : undefined,
      },
    }
  })

  const links: GraphLink[] = edgesRaw.map((rawLink, index) => {
    const link = rawLink as Record<string, unknown>
    return {
      id: String(link.id ?? `link-${index}`),
      source: String(link.source ?? ""),
      target: String(link.target ?? ""),
      label: String(link.label ?? ""),
    }
  })

  return { nodes, links }
}

function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })

  useEffect(() => {
    const element = ref.current
    if (!element) return

    const update = () => {
      setSize({
        width: element.clientWidth,
        height: element.clientHeight,
      })
    }

    update()

    const observer = new ResizeObserver(() => {
      update()
    })
    observer.observe(element)

    return () => {
      observer.disconnect()
    }
  }, [])

  return { ref, size }
}

function initialsFromLabel(label: string): string {
  const parts = label.trim().split(/\s+/).filter(Boolean)
  if (parts.length >= 2) {
    const first = parts[0]?.[0]
    const last = parts[parts.length - 1]?.[0]
    return `${first ?? ""}${last ?? ""}`.toUpperCase() || "?"
  }
  if (parts.length === 1 && parts[0].length >= 2) {
    return parts[0].slice(0, 2).toUpperCase()
  }
  return parts[0]?.[0]?.toUpperCase() ?? "?"
}

function nodeRadius(type: GraphNodeType): number {
  if (type === "personnel") return 8
  if (type === "org") return 6
  if (type === "skill") return 3
  return 5
}

function nodeColor(type: GraphNodeType): string {
  if (type === "personnel") return "#1D9E75"
  if (type === "org") return "#534AB7"
  if (type === "skill") return "#BA7517"
  return "#6B7280"
}

interface GraphCanvasProps {
  graphData: GraphData
  onNodeClick?: (sel: GraphNodeSelection) => void
  onBackgroundClick?: () => void
  selectedNodeId?: string | null
}

export default function GraphCanvas({
  graphData,
  onNodeClick,
  onBackgroundClick,
  selectedNodeId,
}: GraphCanvasProps) {
  const graphRef = useRef<{ zoomToFit: (ms?: number, padding?: number) => void } | null>(null)
  const { ref, size } = useElementSize<HTMLDivElement>()

  useEffect(() => {
    if (!graphRef.current || size.width === 0 || size.height === 0) return
    if (graphData.nodes.length === 0) return

    const timer = window.setTimeout(() => {
      graphRef.current?.zoomToFit(450, 48)
    }, 0)

    return () => window.clearTimeout(timer)
  }, [graphData.nodes.length, size.height, size.width])

  const nodeCanvasObject = useMemo(
    () =>
      (
        node: GraphNode,
        ctx: CanvasRenderingContext2D,
        globalScale: number,
      ) => {
        const radius = nodeRadius(node.type)
        const isSelected = node.id === selectedNodeId

        ctx.save()
        ctx.beginPath()
        ctx.arc(node.x ?? 0, node.y ?? 0, radius, 0, Math.PI * 2)
        ctx.fillStyle = nodeColor(node.type)
        ctx.fill()

        if (isSelected) {
          ctx.lineWidth = Math.max(2, 3 / globalScale)
          ctx.strokeStyle = "rgba(255,255,255,0.95)"
          ctx.stroke()
        }

        if (node.type !== "skill" && radius >= 6) {
          ctx.fillStyle = "#FFFFFF"
          ctx.font = `${Math.max(8, radius * 0.85) / globalScale}px ui-sans-serif, system-ui, sans-serif`
          ctx.textAlign = "center"
          ctx.textBaseline = "middle"
          ctx.fillText(initialsFromLabel(node.label), node.x ?? 0, node.y ?? 0)
        }

        ctx.restore()
      },
    [selectedNodeId],
  )

  return (
    <div
      ref={ref}
      className="border-input bg-card/40 relative h-[min(70vh,600px)] w-full overflow-hidden rounded-lg border"
    >
      {size.width === 0 || size.height === 0 ? null : (
        <ForceGraph2D
          ref={graphRef}
          width={size.width}
          height={size.height}
          graphData={graphData}
          backgroundColor="transparent"
          nodeLabel={(node) => node.label}
          nodeRelSize={1}
          nodeVal={(node) => nodeRadius(node.type)}
          nodeColor={(node) => nodeColor(node.type)}
          linkColor={() => "#88878099"}
          linkWidth={1.2}
          nodeCanvasObject={nodeCanvasObject}
          nodeCanvasObjectMode={() => "replace"}
          onNodeClick={(node: GraphNode) => {
            onNodeClick?.(node)
          }}
          onBackgroundClick={() => {
            onBackgroundClick?.()
          }}
          enableNodeDrag
          cooldownTicks={120}
          d3VelocityDecay={0.25}
        />
      )}

      {graphData.nodes.length === 0 ? (
        <div className="text-muted-foreground pointer-events-none absolute inset-0 flex items-center justify-center text-sm">
          Chưa có node quan hệ trực tiếp.
        </div>
      ) : null}
    </div>
  )
}

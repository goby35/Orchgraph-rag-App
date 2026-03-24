"use client"

import { memo } from "react"
import { Handle, Position, type NodeProps } from "reactflow"

import type { PersonnelNodeData } from "@/types"
import { cn } from "@/lib/utils"

function initialsFromLabel(label: string): string {
  const parts = label.trim().split(/\s+/).filter(Boolean)
  if (parts.length >= 2) {
    const a = parts[0]?.[0]
    const b = parts[parts.length - 1]?.[0]
    return `${a ?? ""}${b ?? ""}`.toUpperCase() || "?"
  }
  if (parts.length === 1 && parts[0].length >= 2) {
    return parts[0].slice(0, 2).toUpperCase()
  }
  return parts[0]?.[0]?.toUpperCase() ?? "?"
}

function PersonnelNode({ data, selected }: NodeProps) {
  const d = data as PersonnelNodeData
  return (
    <div
      className={cn(
        "bg-background flex size-16 cursor-pointer items-center justify-center rounded-full border-2 shadow-sm transition-all select-none relative",
        d.availability ? "border-green-500" : "border-muted-foreground/40",
        selected && "border-primary ring-primary/30 ring-2 shadow-lg scale-110",
      )}
    >
      {/* THÊM 2 DÒNG NÀY ĐỂ NỐI DÂY */}
      <Handle type="target" position={Position.Left} className="w-2 h-2" />
      <span className="text-foreground text-sm font-bold">
        {initialsFromLabel(d.label)}
      </span>
      <Handle type="source" position={Position.Right} className="w-2 h-2" />
    </div>
  )
}

export default memo(PersonnelNode)

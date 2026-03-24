"use client"

import { memo } from "react"
import { Handle, Position, type NodeProps } from "reactflow"
import { cn } from "@/lib/utils"

function GenericNode({ data, type, selected }: NodeProps) {
  // Đổi màu dựa trên loại Node (Skill, Project, Experience...)
  const colorMap: Record<string, string> = {
    skill: "bg-purple-100 border-purple-400 text-purple-800 dark:bg-purple-900/40 dark:border-purple-600 dark:text-purple-200",
    project: "bg-orange-100 border-orange-400 text-orange-800 dark:bg-orange-900/40 dark:border-orange-600 dark:text-orange-200",
    experience: "bg-emerald-100 border-emerald-400 text-emerald-800 dark:bg-emerald-900/40 dark:border-emerald-600 dark:text-emerald-200",
    education: "bg-indigo-100 border-indigo-400 text-indigo-800 dark:bg-indigo-900/40 dark:border-indigo-600 dark:text-indigo-200",
  }

  const defaultColor = "bg-gray-100 border-gray-400 text-gray-800 dark:bg-gray-800 dark:border-gray-600 dark:text-gray-200"
  const theme = colorMap[type] || defaultColor

  return (
    <div
      className={cn(
        "min-w-[80px] max-w-[150px] cursor-pointer rounded-full border-2 px-3 py-1.5 text-center transition-all shadow-sm",
        theme,
        selected && "ring-2 ring-primary/50 shadow-md scale-105"
      )}
    >
      {/* CỰC KỲ QUAN TRỌNG: Phải có Handle thì Edges mới nối được */}
      <Handle type="target" position={Position.Left} className="opacity-0" />
      <p className="truncate text-[10px] font-bold uppercase tracking-wider opacity-70 mb-0.5">
        {type}
      </p>
      <p className="truncate text-xs font-semibold">
        {data.label}
      </p>
      <Handle type="source" position={Position.Right} className="opacity-0" />
    </div>
  )
}

export default memo(GenericNode)
"use client"

import { memo } from "react"
import { Handle, Position, type NodeProps } from "reactflow"
import type { OrgNodeData } from "@/types"
import { cn } from "@/lib/utils"

function OrgNode({ data, selected }: NodeProps) {
  const d = data as OrgNodeData

  return (
    <div
      className={cn(
        // Bắt buộc phải thêm chữ "relative" ở đầu
        "relative bg-blue-50 dark:bg-blue-950/40 min-w-[100px] cursor-pointer rounded-lg border-2 border-blue-300 px-3 py-2 text-center transition-all select-none dark:border-blue-600",
        selected && "border-blue-600 shadow-md dark:border-blue-400",
      )}
    >
      {/* Đầu cắm nhận dây (Target) nằm bên trái */}
      <Handle 
        type="target" 
        position={Position.Left} 
        className="w-2 h-2 !bg-blue-500 border-none" 
      />

      <p className="max-w-[120px] truncate text-xs font-semibold text-blue-900 dark:text-blue-100">
        {d.label}
      </p>
      {d.industry ? (
        <p className="mt-0.5 max-w-[120px] truncate text-[10px] text-blue-700 dark:text-blue-300">
          {d.industry}
        </p>
      ) : null}

      {/* Đầu cắm phát dây (Source) nằm bên phải */}
      <Handle 
        type="source" 
        position={Position.Right} 
        className="w-2 h-2 !bg-blue-500 border-none" 
      />
    </div>
  )
}
export default memo(OrgNode)

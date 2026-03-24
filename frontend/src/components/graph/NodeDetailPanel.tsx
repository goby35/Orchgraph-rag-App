"use client"

import { X } from "lucide-react"
import Link from "next/link"

import { buttonVariants } from "@/lib/variants"
import { cn } from "@/lib/utils"
import type { OrgNodeData, PersonnelNodeData } from "@/types"

import type { GraphNodeSelection } from "./GraphCanvas"

interface NodeDetailPanelProps {
  selection: GraphNodeSelection | null
  onClose: () => void
}

export function NodeDetailPanel({ selection, onClose }: NodeDetailPanelProps) {
  if (!selection) return null

  const { type, data } = selection

  return (
    <aside
      className="bg-card flex w-72 shrink-0 flex-col rounded-lg border shadow-sm"
      aria-label="Chi tiết node"
    >
      <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
        <h2 className="text-sm font-semibold">{type === "org" ? "Tổ chức" : "Ứng viên"}</h2>
        <button
          type="button"
          onClick={onClose}
          className={cn(
            buttonVariants({ variant: "ghost", size: "icon" }),
            "size-8 shrink-0",
          )}
          aria-label="Đóng"
        >
          <X className="size-4" />
        </button>
      </div>
      <div className="flex flex-1 flex-col gap-3 p-3 text-sm">
        {type === "personnel" ? (
          <PersonnelDetailContent
            data={data as PersonnelNodeData}
            id={selection.id}
          />
        ) : (
          <OrgDetailContent data={data as OrgNodeData} />
        )}
      </div>
    </aside>
  )
}

function PersonnelDetailContent({
  data,
  id,
}: {
  data: PersonnelNodeData
  id: string
}) {
  return (
    <>
      <div>
        <p className="text-muted-foreground text-xs">Tên</p>
        <p className="font-medium">{data.label}</p>
      </div>
      {data.summary ? (
        <div>
          <p className="text-muted-foreground text-xs">Tóm tắt</p>
          <p className="line-clamp-4">{data.summary}</p>
        </div>
      ) : null}
      {data.skills && data.skills.length > 0 ? (
        <div>
          <p className="text-muted-foreground text-xs">Kỹ năng</p>
          <div className="mt-1 flex flex-wrap gap-1">
            {data.skills.map((s) => (
              <span
                key={s}
                className="bg-muted rounded px-1.5 py-0.5 text-xs"
              >
                {s}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      <div className="mt-auto pt-2">
        <p className="text-muted-foreground mb-1 text-xs">
          {data.availability ? "Đã kết nối (accepted)" : "Chưa xác nhận kết nối"}
        </p>
        <Link
          href={`/interview/${encodeURIComponent(id)}`}
          className={cn(
            buttonVariants({ variant: "default", size: "sm" }),
            "w-full text-center",
          )}
        >
          Phỏng vấn
        </Link>
      </div>
    </>
  )
}

function OrgDetailContent({ data }: { data: OrgNodeData }) {
  return (
    <>
      <div>
        <p className="text-muted-foreground text-xs">Tên</p>
        <p className="font-medium">{data.label}</p>
      </div>
      {data.industry ? (
        <div>
          <p className="text-muted-foreground text-xs">Ngành</p>
          <p>{data.industry}</p>
        </div>
      ) : (
        <p className="text-muted-foreground text-xs">Không có thông tin ngành.</p>
      )}
    </>
  )
}

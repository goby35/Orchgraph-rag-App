"use client"

import Link from "next/link"
import { X } from "lucide-react"

import { buttonVariants } from "@/lib/variants"
import { cn } from "@/lib/utils"

import type { GraphData, GraphNodeSelection } from "./GraphCanvas"

interface NodeDetailPanelProps {
  selection: GraphNodeSelection | null
  graphData: GraphData
  onClose: () => void
}

export function NodeDetailPanel({ selection, graphData, onClose }: NodeDetailPanelProps) {
  if (!selection) return null

  const type = selection.type
  const label =
    type === "personnel" && typeof selection.data.public_full_name === "string"
      ? selection.data.public_full_name
      : selection.data.label || selection.label
  const summary = typeof selection.data.summary === "string" ? selection.data.summary : ""
  const skills = Array.isArray(selection.data.skills)
    ? selection.data.skills.map(String).slice(0, 5)
    : []
  const initials = initialsFromLabel(label)
  const personnelCount = countConnectedPersonnel(graphData, selection.id)

  return (
    <aside
      className="bg-card flex w-full shrink-0 flex-col rounded-lg border shadow-sm lg:w-[320px] animate-in slide-in-from-right-4 duration-200"
      aria-label="Chi tiết node"
    >
      <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
        <h2 className="text-sm font-semibold">
          {type === "org" ? "Tổ chức" : type === "skill" ? "Kỹ năng" : "Nhân sự"}
        </h2>
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
            id={selection.id}
            label={label}
            initials={initials}
            summary={truncateText(summary, 120)}
            skills={skills}
          />
        ) : type === "org" ? (
          <OrgDetailContent label={label} personnelCount={personnelCount} />
        ) : (
          <SkillDetailContent label={label} personnelCount={personnelCount} />
        )}
      </div>
    </aside>
  )
}

function PersonnelDetailContent({
  id,
  label,
  initials,
  summary,
  skills,
}: {
  id: string
  label: string
  initials: string
  summary: string
  skills: string[]
}) {
  const interviewHref = `/interview?${new URLSearchParams({
    personnelId: id,
    jobTitle: "",
    sessionId: "new",
  }).toString()}`

  return (
    <>
      <div className="flex items-center gap-3">
        <div className="bg-primary/10 text-primary flex size-12 items-center justify-center rounded-full font-semibold">
          {initials}
        </div>
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs">Tên</p>
          <p className="truncate font-medium">{label}</p>
        </div>
      </div>
      {summary ? (
        <div>
          <p className="text-muted-foreground text-xs">Professional summary</p>
          <p className="text-sm leading-6">{summary}</p>
        </div>
      ) : null}
      {skills.length > 0 ? (
        <div>
          <p className="text-muted-foreground text-xs">Top skills</p>
          <div className="mt-1 flex flex-wrap gap-1">
            {skills.map((skill) => (
              <span key={skill} className="bg-muted rounded-full px-2 py-0.5 text-xs">
                {skill}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      <div className="mt-auto flex flex-col gap-2 pt-2">
        <Link
          href={interviewHref}
          className={cn(
            buttonVariants({ variant: "default", size: "sm" }),
            "w-full text-center",
          )}
        >
          Phỏng vấn Digital Twin
        </Link>
        <Link
          href={`/interview/${encodeURIComponent(id)}`}
          className={cn(
            buttonVariants({ variant: "outline", size: "sm" }),
            "w-full text-center",
          )}
        >
          Xem hồ sơ đầy đủ
        </Link>
      </div>
    </>
  )
}

function OrgDetailContent({
  label,
  personnelCount,
}: {
  label: string
  personnelCount: number
}) {
  return (
    <>
      <div>
        <p className="text-muted-foreground text-xs">Tên</p>
        <p className="font-medium">{label}</p>
      </div>
      <div>
        <p className="text-muted-foreground text-xs">Personnel liên quan</p>
        <p className="font-medium">{personnelCount}</p>
      </div>
    </>
  )
}

function SkillDetailContent({
  label,
  personnelCount,
}: {
  label: string
  personnelCount: number
}) {
  return (
    <>
      <div>
        <p className="text-muted-foreground text-xs">Tên skill</p>
        <p className="font-medium">{label}</p>
      </div>
      <div>
        <p className="text-muted-foreground text-xs">Personnel có skill này</p>
        <p className="font-medium">{personnelCount}</p>
      </div>
    </>
  )
}

function truncateText(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value
  return `${value.slice(0, maxLength).trimEnd()}…`
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

function countConnectedPersonnel(graphData: GraphData, nodeId: string): number {
  const personnelIds = new Set(
    graphData.nodes.filter((node) => node.type === "personnel").map((node) => node.id),
  )
  const connected = new Set<string>()

  for (const link of graphData.links) {
    const sourceId = typeof link.source === "string" ? link.source : link.source.id
    const targetId = typeof link.target === "string" ? link.target : link.target.id

    if (sourceId === nodeId && personnelIds.has(targetId)) {
      connected.add(targetId)
    }

    if (targetId === nodeId && personnelIds.has(sourceId)) {
      connected.add(sourceId)
    }
  }

  return connected.size
}

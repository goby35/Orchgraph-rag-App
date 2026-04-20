"use client"

import { useMemo, useState, type MouseEvent } from "react"
import { useQuery } from "@tanstack/react-query"
import { Search, Trash2 } from "lucide-react"
import Link from "next/link"

import { Skeleton } from "@/components/ui/skeleton"
import { Input } from "@/components/ui/input"
import { getInterviewSessions, type InterviewSession } from "@/lib/api/chat"
import { getConnectionStatuses } from "@/lib/api/interview"
import { cn } from "@/lib/utils"

interface SessionSidebarProps {
  activeSessionId: string | null
  currentOrgId: string
  onSessionSelect: (session: InterviewSession) => void | Promise<void>
  onSessionDelete?: (session: InterviewSession) => void | Promise<void>
  className?: string
}

function getInitials(name: string): string {
  const parts = name
    .split(" ")
    .map((part) => part.trim())
    .filter(Boolean)

  if (parts.length === 0) return "?"

  return parts
    .slice(-2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("") || "?"
}

function timeAgo(dateStr: string): string {
  const date = new Date(dateStr)
  if (Number.isNaN(date.getTime())) return ""

  const diffMs = Date.now() - date.getTime()
  const diffMinutes = Math.floor(diffMs / 60_000)
  const diffHours = Math.floor(diffMs / 3_600_000)
  const diffDays = Math.floor(diffMs / 86_400_000)

  if (diffMinutes < 1) return "vừa xong"
  if (diffMinutes < 60) return `${diffMinutes} phút trước`
  if (diffHours < 24) return `${diffHours} giờ trước`
  return `${diffDays} ngày trước`
}

function formatJobTitle(jobTitle: string | null | undefined): string {
  const normalized = jobTitle?.trim()
  return normalized ? normalized : "Vị trí chưa xác định"
}

export function SessionSidebar({
  activeSessionId,
  currentOrgId,
  onSessionSelect,
  onSessionDelete,
  className,
}: SessionSidebarProps) {
  const [searchValue, setSearchValue] = useState("")
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null)

  const sessionsQuery = useQuery({
    queryKey: ["interview-sessions", currentOrgId],
    queryFn: () => getInterviewSessions(currentOrgId),
    enabled: Boolean(currentOrgId),
    staleTime: 30_000,
    refetchOnWindowFocus: true,
  })

  const sessions = useMemo(
    () => [...(sessionsQuery.data ?? [])].sort(
      (a, b) => +new Date(b.created_at) - +new Date(a.created_at),
    ),
    [sessionsQuery.data],
  )

  const filteredSessions = useMemo(
    () => sessions.filter((session) => {
      const needle = searchValue.trim().toLowerCase()
      if (!needle) return true
      const personnelName = String(session.personnel_name ?? "").toLowerCase()
      const jobTitle = String(session.job_title ?? "").toLowerCase()
      return (
        personnelName.includes(needle) ||
        jobTitle.includes(needle)
      )
    }),
    [searchValue, sessions],
  )

  const personnelIds = useMemo(
    () => Array.from(new Set(filteredSessions.map((session) => session.personnel_id).filter(Boolean))),
    [filteredSessions],
  )

  const connectionBatchQuery = useQuery({
    queryKey: ["connection-statuses", currentOrgId, personnelIds],
    queryFn: () => getConnectionStatuses(personnelIds),
    enabled: personnelIds.length > 0,
    staleTime: 30_000,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
  })

  const connectionByPersonId = useMemo(() => {
    const statuses = connectionBatchQuery.data?.statuses ?? {}
    return new Map(personnelIds.map((personnelId) => [personnelId, statuses[personnelId] ?? null]))
  }, [connectionBatchQuery.data?.statuses, personnelIds])

  const handleSessionClick = async (session: InterviewSession) => {
    await onSessionSelect(session)
  }

  const handleDeleteClick = async (event: MouseEvent<HTMLButtonElement>, session: InterviewSession) => {
    event.preventDefault()
    event.stopPropagation()

    if (!onSessionDelete) return
    const confirmed = window.confirm(`Xóa phiên phỏng vấn của ${session.personnel_name}?`)
    if (!confirmed) return

    try {
      setDeletingSessionId(session.session_id)
      await onSessionDelete(session)
    } catch {
      window.alert("Không thể xóa phiên lúc này. Vui lòng thử lại.")
    } finally {
      setDeletingSessionId((current) => (current === session.session_id ? null : current))
    }
  }

  const renderSessionCard = (session: InterviewSession) => {
    const active = session.session_id === activeSessionId
    const connectionStatus = connectionByPersonId.get(session.personnel_id) ?? null
    const initials = getInitials(session.personnel_name || session.personnel_id)
    const lastMessage = session.last_message?.trim() || "Chưa có tin nhắn"
    const sessionTime = timeAgo(session.created_at)

    return (
      <div
        key={session.session_id}
        role="button"
        tabIndex={0}
        onClick={() => { void handleSessionClick(session) }}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault()
            void handleSessionClick(session)
          }
        }}
        className={cn(
          "block w-full rounded-xl border bg-background px-3 py-2 text-left transition-colors hover:bg-accent/60",
          active && "border-l-4 border-l-primary bg-primary/5",
          "cursor-pointer",
        )}
      >
        <div className="flex items-start gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold text-foreground">
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-foreground">
                  {session.personnel_name}
                </p>
                <p className="truncate text-xs text-muted-foreground">
                  {formatJobTitle(session.job_title)}
                </p>
              </div>
              <span
                className={cn(
                  "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium",
                  connectionStatus === "accepted"
                    ? "bg-emerald-50 text-emerald-700"
                    : "bg-muted text-muted-foreground",
                )}
              >
                {connectionStatus === "accepted" ? "● Đã kết nối" : "○ Chưa kết nối"}
              </span>
            </div>
              {onSessionDelete ? (
                <div className="mt-1 flex justify-end">
                  <button
                    type="button"
                    onClick={(event) => { void handleDeleteClick(event, session) }}
                    disabled={deletingSessionId === session.session_id}
                    className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-red-600 transition-colors hover:bg-red-50"
                    aria-label={`Xóa phiên của ${session.personnel_name}`}
                  >
                    <Trash2 className="size-3.5" />
                    {deletingSessionId === session.session_id ? "Đang xóa..." : "Xóa phiên"}
                  </button>
                </div>
              ) : null}
            <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">
              {session.message_count > 0
                ? `${session.message_count} tin nhắn${sessionTime ? ` · ${sessionTime}` : ""}`
                : "Chưa có tin nhắn"}
            </p>
            {session.message_count > 0 ? (
              <p className="mt-1 line-clamp-2 text-xs text-muted-foreground/90">
                {lastMessage}
              </p>
            ) : null}
          </div>
        </div>
      </div>
    )
  }

  return (
    <aside
      className={cn(
        "flex h-full w-80 shrink-0 flex-col border-r bg-muted/15",
        className,
      )}
    >
      <div className="border-b px-4 py-4">
        <p className="text-sm font-semibold">Phiên phỏng vấn</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Danh sách theo thời gian truy cập gần nhất
        </p>
      </div>

      <div className="border-b px-3 py-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchValue}
            onChange={(event) => setSearchValue(event.target.value)}
            placeholder="Tìm phiên phỏng vấn..."
            className="h-9 pl-8"
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {sessionsQuery.isLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-20 rounded-xl" />
            <Skeleton className="h-20 rounded-xl" />
            <Skeleton className="h-20 rounded-xl" />
          </div>
        ) : filteredSessions.length === 0 ? (
          <div className="rounded-xl border bg-background p-4 text-sm text-muted-foreground">
            <p>Chưa có phiên phỏng vấn nào. Tìm ứng viên để bắt đầu.</p>
            <Link
              href="/search"
              className="mt-3 inline-flex rounded-md border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-accent"
            >
              Đi tới trang tìm kiếm
            </Link>
          </div>
        ) : (
          <div className="space-y-2">
            {filteredSessions.map((session) => renderSessionCard(session))}
          </div>
        )}
      </div>
    </aside>
  )
}
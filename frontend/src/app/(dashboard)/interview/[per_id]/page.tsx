'use client'
import { use, useMemo, useState }       from 'react'
import { useSearchParams } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { toast }               from "sonner"
import ChatWindow              from '@/components/chat/ChatWindow'
import BookingModal            from '@/components/scheduling/BookingModal'
import ConnectionStatusBadge   from '@/components/chat/ConnectionStatusBadge'
import { getConnectionStatus, sendInterviewRequest, getPersonnelProfile } from "@/lib/api/interview"
import type { ConnectionStatus } from "@/lib/api/interview"
import { getSessionFitSummary } from "@/lib/api/chat"
import { useAuthStore } from '@/store/auth.store'
import { cn }                  from '@/lib/utils'

export default function InterviewPage({ params }: { params: Promise<{ per_id: string }> }) {
  const { per_id }      = use(params)
  const searchParams = useSearchParams()
  const [bookingOpen, setBookingOpen] = useState(false)
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const queryClient     = useQueryClient()
  const orgNeoId = useAuthStore((s) => s.neoId) ?? ""

  const rawJobTitle = searchParams.get('jobTitle')?.trim() ?? ''
  const requestedSessionId = searchParams.get('sessionId')
  const shouldCreateSession = requestedSessionId === 'new'
  const requestedSessionIdOrNull = requestedSessionId && requestedSessionId !== "new"
    ? requestedSessionId
    : null

  const targetSessionId = activeSessionId || requestedSessionIdOrNull

  // Personnel profile
  const { data: profileData } = useQuery({
    queryKey: ["personnel-profile", per_id],
    queryFn:  () => getPersonnelProfile(per_id),
    staleTime: 5 * 60 * 1000,
  })

  const displayName = profileData?.name ?? per_id
  const jobTitle = rawJobTitle || 'Vị trí chưa xác định'
  const headerTitle = `Phỏng vấn ${displayName} · ${jobTitle}`
  const subtitle = `Digital Twin Interview · ${new Date().toLocaleDateString('vi-VN', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })}`
  const initials    = displayName
    .split(" ")
    .filter(Boolean)
    .slice(-2)
    .map((w: string) => w[0])
    .join("")
    .toUpperCase() || per_id.replace("P_", "")

  // Connection status
  const { data: connData } = useQuery({
    queryKey: ["connection-status", per_id],
    queryFn:  () => getConnectionStatus(per_id),
    staleTime: 30_000,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
  })
  const connectionStatus: ConnectionStatus = connData?.status ?? null

  const fitSummaryQuery = useQuery({
    queryKey: ["session-fit-summary", orgNeoId, targetSessionId],
    queryFn: () => getSessionFitSummary(orgNeoId, targetSessionId as string),
    enabled: Boolean(orgNeoId && targetSessionId),
    staleTime: 5 * 60 * 1000,
  })

  const fitSummaryText = useMemo(() => {
    const text = fitSummaryQuery.data?.fit_summary?.trim()
    if (text) return text
    if (!targetSessionId) {
      return "Summary phù hợp JD sẽ xuất hiện ở đây sau khi phiên phỏng vấn được tạo."
    }
    return "Chưa đủ dữ liệu để tạo diễn giải mức độ phù hợp cho phiên này."
  }, [fitSummaryQuery.data?.fit_summary, targetSessionId])

  // Gửi lời mời
  const requestMut = useMutation({
    mutationFn: () => sendInterviewRequest(per_id),
    onSuccess: () => {
      toast.success("Đã gửi lời mời phỏng vấn!")
      queryClient.invalidateQueries({ queryKey: ["connection-status", per_id] })
    },
    onError: () => toast.error("Không thể gửi lời mời. Thử lại sau."),
  })

  return (
    <div className="flex h-[calc(100vh-3.5rem)] gap-4 lg:gap-5">

      {/* Profile panel */}
      <div className="hidden w-72 flex-shrink-0 flex-col gap-3 rounded-2xl border border-border/70 bg-card/90 p-4 shadow-sm md:flex">
        {/* Avatar */}
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-primary/12 text-xl font-semibold text-primary">
          {initials}
        </div>

        {/* ID + connection badge */}
        <div className="flex flex-col items-center gap-2">
          <p className="text-sm font-semibold tracking-tight">{displayName}</p>
          <ConnectionStatusBadge status={connectionStatus} />
        </div>

        <div className="rounded-xl border border-border/70 bg-muted/30 p-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            LLM Fit Summary
          </p>
          <p className="mt-1 text-xs leading-5 text-foreground/90">
            {fitSummaryQuery.isLoading ? "Đang phân tích mức độ phù hợp..." : fitSummaryText}
          </p>
        </div>

        {/* Nút mời phỏng vấn */}
        <div className="mt-auto space-y-2">
          {connectionStatus === null && (
            <button
              onClick={() => requestMut.mutate()}
              disabled={requestMut.isPending}
              className={cn(
                "w-full rounded-xl px-3 py-2 text-sm font-medium transition-all duration-200",
                "bg-primary text-primary-foreground hover:bg-primary/90",
                "disabled:opacity-50 disabled:cursor-not-allowed",
              )}
            >
              {requestMut.isPending ? "Đang gửi..." : "Mời phỏng vấn thực tế"}
            </button>
          )}

          {connectionStatus === "pending" && (
            <p className="text-xs text-center text-muted-foreground">
              Đã gửi lời mời — chờ ứng viên xác nhận
            </p>
          )}

          {connectionStatus === "accepted" && (
            <button
              onClick={() => setBookingOpen(true)}
              className={cn(
                "w-full rounded-xl px-3 py-2 text-sm font-medium transition-all duration-200",
                "bg-primary text-primary-foreground hover:bg-primary/90",
              )}
            >
              Đặt lịch phỏng vấn
            </button>
          )}
        </div>
      </div>

      {/* Chat */}
      <div className="flex-1 overflow-hidden rounded-2xl border border-border/70 bg-card/85 shadow-sm">
        <ChatWindow
          perNeoId={per_id}
          title={headerTitle}
          subtitle={subtitle}
          requestedSessionId={requestedSessionId}
          createSessionOnMount={shouldCreateSession}
          initialJobTitle={rawJobTitle}
          onSessionResolved={setActiveSessionId}
          onBookInterview={
            connectionStatus === "accepted"
              ? () => setBookingOpen(true)
              : undefined
          }
        />
      </div>

      {/* Booking Modal */}
      <BookingModal
        perNeoId={per_id}
        open={bookingOpen}
        onClose={() => setBookingOpen(false)}
      />
    </div>
  )
}
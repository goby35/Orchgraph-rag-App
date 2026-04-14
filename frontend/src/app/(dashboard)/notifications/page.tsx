"use client"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useRouter }   from "next/navigation"
import { useState }    from "react"
import { toast }       from "sonner"
import { useAuthStore } from "@/store/auth.store"
import {
  getNotifications,
  markNotificationRead,
  markAllNotificationsRead,
} from "@/lib/api/notification"
import { respondConnection } from "@/lib/api/connect"
import { acceptInterviewRequest, rejectInterviewRequest } from "@/lib/api/interview"
import { useRealtimeNotifications } from "@/hooks/useRealtimeNotifications"
import { formatDate } from "@/lib/utils"
import { cn }         from "@/lib/utils"

interface NotificationItem {
  id:                 string
  type?:              string
  title:              string
  body?:              string | null
  is_read:            boolean
  created_at:         string
  payload?:           Record<string, unknown>
}

function InterviewRequestActions({ notification }: { notification: NotificationItem }) {
  const queryClient = useQueryClient()

  const acceptMut = useMutation({
    mutationFn: () => acceptInterviewRequest(notification.payload?.per_neo4j_id as string ?? ""),
    onSuccess: () => {
      toast.success("Đã chấp nhận lời mời phỏng vấn!")
      queryClient.invalidateQueries({ queryKey: ["notifications"] })
      queryClient.invalidateQueries({ queryKey: ["unread-count"] })
    },
    onError: () => toast.error("Không thể chấp nhận. Thử lại sau."),
  })

  const rejectMut = useMutation({
    mutationFn: () => rejectInterviewRequest(notification.payload?.per_neo4j_id as string ?? ""),
    onSuccess: () => {
      toast.info("Đã từ chối lời mời.")
      queryClient.invalidateQueries({ queryKey: ["notifications"] })
      queryClient.invalidateQueries({ queryKey: ["unread-count"] })
    },
    onError: () => toast.error("Không thể từ chối. Thử lại sau."),
  })

  return (
    <div className="flex gap-2 mt-2">
      <button
        onClick={(e) => { e.stopPropagation(); acceptMut.mutate() }}
        disabled={acceptMut.isPending || rejectMut.isPending}
        className="text-xs px-3 py-1.5 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
      >
        {acceptMut.isPending ? "Đang xử lý..." : "Chấp nhận"}
      </button>
      <button
        onClick={(e) => { e.stopPropagation(); rejectMut.mutate() }}
        disabled={acceptMut.isPending || rejectMut.isPending}
        className="text-xs px-3 py-1.5 rounded-md border hover:bg-muted disabled:opacity-50"
      >
        {rejectMut.isPending ? "Đang xử lý..." : "Từ chối"}
      </button>
    </div>
  )
}

export default function NotificationsPage() {
  const router      = useRouter()
  const queryClient = useQueryClient()
  const neoId       = useAuthStore(s => s.neoId)
  const [respondingId, setRespondingId] = useState<string | null>(null)

  // Realtime subscription
  useRealtimeNotifications(neoId)

  const { data: notifications = [], isLoading } = useQuery({
    queryKey: ["notifications"],
    queryFn:  () => getNotifications(false, 50),
    select:   (data) => data as NotificationItem[],
  })

  const markReadMut = useMutation({
    mutationFn: markNotificationRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] })
      queryClient.invalidateQueries({ queryKey: ["unread-count"] })
    },
  })

  const markAllMut = useMutation({
    mutationFn: markAllNotificationsRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] })
      queryClient.invalidateQueries({ queryKey: ["unread-count"] })
      toast.success("Đã đánh dấu tất cả là đã đọc")
    },
  })

  const handleClick = (n: NotificationItem) => {
    if (!n.is_read) markReadMut.mutate(n.id)
    const redirectTo = n.payload?.redirect_to
    if (typeof redirectTo === "string") {
      router.push(redirectTo)
      return
    }

    if (typeof n.type === "string" && n.type.startsWith("schedule_")) {
      router.push("/schedule")
    }
  }

  const handleRespondConnection = async (
    notification: NotificationItem,
    action: "accept" | "decline",
  ) => {
    if (!neoId) {
      toast.error("Khong tim thay tai khoan hien tai")
      return
    }
    const orgId = String(notification.payload?.org_id ?? "")
    if (!orgId) {
      toast.error("Thieu org_id trong notification")
      return
    }

    setRespondingId(notification.id)
    try {
      await respondConnection({
        org_id: orgId,
        personnel_id: neoId,
        action,
      })

      await markNotificationRead(notification.id)
      queryClient.invalidateQueries({ queryKey: ["notifications"] })
      queryClient.invalidateQueries({ queryKey: ["unread-count"] })

      if (action === "accept") {
        toast.success("Da chap nhan ket noi")
      } else {
        toast.success("Da tu choi ket noi")
      }
    } catch {
      toast.error("Khong the phan hoi ket noi")
    } finally {
      setRespondingId(null)
    }
  }

  const unreadCount = notifications.filter(n => !n.is_read).length

  // Group theo ngày
  const grouped = notifications.reduce<Record<string, NotificationItem[]>>(
    (acc, n) => {
      const day = new Date(n.created_at).toLocaleDateString("vi-VN", {
        weekday: "long",
        day:     "2-digit",
        month:   "2-digit",
        year:    "numeric",
      })
      if (!acc[day]) acc[day] = []
      acc[day].push(n)
      return acc
    },
    {},
  )

  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-8">

      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Thông báo</h1>
          {unreadCount > 0 && (
            <p className="mt-0.5 text-sm text-muted-foreground">
              {unreadCount} chưa đọc
            </p>
          )}
        </div>
        {unreadCount > 0 && (
          <button
            onClick={() => markAllMut.mutate()}
            disabled={markAllMut.isPending}
            className="rounded-lg px-2 py-1 text-sm font-medium text-primary transition-colors hover:bg-primary/10 disabled:opacity-50"
          >
            {markAllMut.isPending ? "Đang xử lý..." : "Đánh dấu tất cả đã đọc"}
          </button>
        )}
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="space-y-3">
          {[1, 2, 3].map(i => (
            <div key={i} className="animate-pulse space-y-2 rounded-2xl border border-border/70 bg-card/80 p-4">
              <div className="h-4 bg-muted rounded w-1/2" />
              <div className="h-3 bg-muted rounded w-3/4" />
            </div>
          ))}
        </div>
      )}

      {/* Empty state */}
      {!isLoading && notifications.length === 0 && (
        <div className="flex flex-col items-center justify-center space-y-3 rounded-2xl border border-border/70 bg-card/85 py-16">
          {/* Bell icon */}
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted/70">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-6 w-6 text-muted-foreground"
              fill="none" viewBox="0 0 24 24" stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6 6 0 00-9.33-5M9 17H4l1.405-1.405A2.032 2.032 0 006 14.158V11a6 6 0 016-6m0 0V4m0 1a2 2 0 100 4 2 2 0 000-4z"
              />
            </svg>
          </div>
          <p className="text-sm text-muted-foreground">Không có thông báo nào</p>
        </div>
      )}

      {/* Grouped list */}
      {!isLoading && Object.entries(grouped).map(([day, items]) => (
        <div key={day} className="space-y-2">
          {/* Day label */}
          <p className="text-xs font-medium text-muted-foreground capitalize">
            {day}
          </p>

          <div className="space-y-1.5">
            {items.map(n => (
              <div
                key={n.id}
                onClick={() => handleClick(n)}
                className={cn(
                  "w-full rounded-2xl border px-4 py-3 text-left",
                  "transition-all duration-200 hover:shadow-sm",
                  n.is_read
                    ? "border-border/70 bg-card/85 hover:bg-muted/35"
                    : "border-primary/25 bg-primary/8 hover:bg-primary/12",
                )}
              >
                <div className="flex items-start gap-3">
                  {/* Unread dot */}
                    <span className={cn(
                      "mt-1.5 h-2 w-2 shrink-0 rounded-full",
                    n.is_read ? "bg-transparent" : "bg-primary",
                  )} />

                  <div className="flex-1 min-w-0 space-y-0.5">
                    <p className={cn(
                      "text-sm truncate",
                      !n.is_read && "font-semibold",
                    )}>
                      {n.title}
                    </p>
                    {n.body && (
                      <p className="text-xs text-muted-foreground line-clamp-2">
                        {n.body}
                      </p>
                    )}
                    {n.type === "interview_request" &&  (
                      <InterviewRequestActions notification={n} />
                    )}
                    {n.type === "connection_request" && (
                      <div className="mt-2 flex gap-2">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            void handleRespondConnection(n, "accept")
                          }}
                          disabled={respondingId === n.id}
                          className="rounded-xl bg-primary px-3 py-1.5 text-xs text-primary-foreground transition-all duration-200 hover:scale-[1.02] hover:bg-primary/92 active:scale-[0.98] disabled:opacity-50"
                        >
                          {respondingId === n.id ? "Dang xu ly..." : "Chap nhan"}
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            void handleRespondConnection(n, "decline")
                          }}
                          disabled={respondingId === n.id}
                          className="rounded-xl border border-border/80 px-3 py-1.5 text-xs transition-all duration-200 hover:scale-[1.02] hover:bg-muted/55 active:scale-[0.98] disabled:opacity-50"
                        >
                          {respondingId === n.id ? "Dang xu ly..." : "Tu choi"}
                        </button>
                      </div>
                    )}
                    {n.type === "auto_connected" && (
                      <p className="text-sm text-muted-foreground mt-1">
                        Ket noi da duoc thiet lap tu dong dua tren do phu hop cao.
                      </p>
                    )}
                  </div>

                  <span className="mt-0.5 shrink-0 whitespace-nowrap text-[11px] text-muted-foreground">
                    {formatDate(n.created_at)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}

    </div>
  )
}
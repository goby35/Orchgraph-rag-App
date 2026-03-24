"use client"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useRouter }   from "next/navigation"
import { toast }       from "sonner"
import { useAuthStore } from "@/store/auth.store"
import {
  getNotifications,
  markNotificationRead,
  markAllNotificationsRead,
} from "@/lib/api/notification"
import { useRealtimeNotifications } from "@/hooks/useRealtimeNotifications"
import { formatDate } from "@/lib/utils"
import { cn }         from "@/lib/utils"

interface NotificationItem {
  id:                 string
  title:              string
  body?:              string | null
  is_read:            boolean
  created_at:         string
  payload?:           Record<string, unknown>
}

export default function NotificationsPage() {
  const router      = useRouter()
  const queryClient = useQueryClient()
  const neoId       = useAuthStore(s => s.neoId)

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
    if (typeof redirectTo === "string") router.push(redirectTo)
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
    <div className="max-w-2xl mx-auto py-8 px-4 space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Thông báo</h1>
          {unreadCount > 0 && (
            <p className="text-sm text-muted-foreground mt-0.5">
              {unreadCount} chưa đọc
            </p>
          )}
        </div>
        {unreadCount > 0 && (
          <button
            onClick={() => markAllMut.mutate()}
            disabled={markAllMut.isPending}
            className="text-sm text-primary hover:underline disabled:opacity-50"
          >
            {markAllMut.isPending ? "Đang xử lý..." : "Đánh dấu tất cả đã đọc"}
          </button>
        )}
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="space-y-3">
          {[1, 2, 3].map(i => (
            <div key={i} className="border rounded-lg p-4 space-y-2 animate-pulse">
              <div className="h-4 bg-muted rounded w-1/2" />
              <div className="h-3 bg-muted rounded w-3/4" />
            </div>
          ))}
        </div>
      )}

      {/* Empty state */}
      {!isLoading && notifications.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 space-y-3">
          {/* Bell icon */}
          <div className="h-12 w-12 rounded-full bg-muted flex items-center justify-center">
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
              <button
                key={n.id}
                onClick={() => handleClick(n)}
                className={cn(
                  "w-full text-left rounded-lg border px-4 py-3",
                  "transition-colors hover:bg-muted/50",
                  n.is_read
                    ? "bg-background border-border"
                    : "bg-primary/5 border-primary/20",
                )}
              >
                <div className="flex items-start gap-3">
                  {/* Unread dot */}
                  <span className={cn(
                    "mt-1.5 h-2 w-2 rounded-full shrink-0",
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
                  </div>

                  <span className="text-[11px] text-muted-foreground whitespace-nowrap shrink-0 mt-0.5">
                    {formatDate(n.created_at)}
                  </span>
                </div>
              </button>
            ))}
          </div>
        </div>
      ))}

    </div>
  )
}
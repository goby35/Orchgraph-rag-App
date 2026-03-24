"use client"

import { useQuery } from "@tanstack/react-query"
import { Bell } from "lucide-react"
import Link from "next/link"

import { useRealtimeNotifications } from "@/hooks/useRealtimeNotifications"
import { getUnreadCount } from "@/lib/api"
import { buttonVariants } from "@/lib/variants"
import { cn } from "@/lib/utils"
import { useAuthStore } from "@/store/auth.store"

function formatBadgeCount(count: number): string {
  if (count > 9) return "9+"
  return String(count)
}

export function NotificationBell() {
  const neoId = useAuthStore((s) => s.neoId)
  useRealtimeNotifications(neoId)

  const { data: count = 0 } = useQuery({
    queryKey: ["unread-count"],
    queryFn: getUnreadCount,
    refetchInterval: 30_000,
  })

  return (
    <Link
      href="/notifications"
      className={cn(
        buttonVariants({ variant: "ghost", size: "icon" }),
        "relative shrink-0",
      )}
      aria-label={`Thông báo${count > 0 ? ` (${count} chưa đọc)` : ""}`}
    >
      <Bell className="size-5" aria-hidden />
      {count > 0 ? (
        <span
          className="bg-destructive text-destructive-foreground absolute -right-0.5 -top-0.5 flex h-[1.125rem] min-w-[1.125rem] items-center justify-center rounded-full px-1 text-[10px] font-semibold leading-none"
          aria-hidden
        >
          {formatBadgeCount(count)}
        </span>
      ) : null}
    </Link>
  )
}

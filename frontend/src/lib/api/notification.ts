import type { paths } from "@/types/api"

import type { NotificationPayload } from "@/types"

import { apiClient } from "./client"

type UnreadCountResponse =
  paths["/notification/unread-count"]["get"]["responses"]["200"]["content"]["application/json"]

function countFromUnreadResponse(data: UnreadCountResponse): number {
  if (typeof data === "object" && data !== null && "count" in data) {
    const c = (data as { count: unknown }).count
    if (typeof c === "number" && Number.isFinite(c)) return c
  }
  return 0
}

export const getNotifications = (
  unreadOnly = false,
  limit = 20,
): Promise<NotificationPayload[]> =>
  apiClient
    .get<NotificationPayload[]>("/notification", {
      params: { unread_only: unreadOnly, limit },
    })
    .then((r) => r.data)

export const markNotificationRead = (id: string) =>
  apiClient.patch(`/notification/${encodeURIComponent(id)}/read`)

export const markAllNotificationsRead = () =>
  apiClient.patch("/notification/read-all")

export const getUnreadCount = (): Promise<number> =>
  apiClient
    .get<UnreadCountResponse>("/notification/unread-count")
    .then((r) => countFromUnreadResponse(r.data))

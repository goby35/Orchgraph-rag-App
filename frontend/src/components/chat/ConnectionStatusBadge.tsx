// src/components/chat/ConnectionStatusBadge.tsx
import { cn } from "@/lib/utils"
import type { ConnectionStatus } from "@/lib/api/interview"

export default function ConnectionStatusBadge({
  status,
}: {
  status: ConnectionStatus
}) {
  if (status === null) {
    return (
      <span className="text-xs rounded-full px-2.5 py-0.5 bg-gray-100 text-gray-500">
        Chưa kết nối
      </span>
    )
  }
  return (
    <span className={cn(
      "text-xs rounded-full px-2.5 py-0.5 font-medium",
      status === "accepted"   && "bg-green-100 text-green-700",
      status === "pending"    && "bg-amber-100 text-amber-700",
      (status === "cancelled" || status === "declined") && "bg-red-100 text-red-600",
    )}>
      {status === "accepted"  && "Đã kết nối"}
      {status === "pending"   && "Chờ chấp nhận"}
      {status === "cancelled" && "Đã hủy"}
      {status === "declined"  && "Đã từ chối"}
    </span>
  )
}
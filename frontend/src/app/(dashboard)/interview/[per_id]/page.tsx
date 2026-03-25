'use client'
import { use, useState }       from 'react'
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { toast }               from "sonner"
import { useAuthStore }        from '@/store/auth.store'
import ChatWindow              from '@/components/chat/ChatWindow'
import BookingModal            from '@/components/scheduling/BookingModal'
import ConnectionStatusBadge   from '@/components/chat/ConnectionStatusBadge'
import { getConnectionStatus, sendInterviewRequest, getPersonnelProfile } from "@/lib/api/interview"
import type { ConnectionStatus } from "@/lib/api/interview"
import { cn }                  from '@/lib/utils'

export default function InterviewPage({ params }: { params: Promise<{ per_id: string }> }) {
  const { per_id }      = use(params)
  const [bookingOpen, setBookingOpen] = useState(false)
  const queryClient     = useQueryClient()

  // Personnel profile
  const { data: profileData } = useQuery({
    queryKey: ["personnel-profile", per_id],
    queryFn:  () => getPersonnelProfile(per_id),
    staleTime: 5 * 60 * 1000,
  })

  const displayName = profileData?.name ?? per_id
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
  })
  const connectionStatus: ConnectionStatus = connData?.status ?? null

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
    <div className="flex h-[calc(100vh-3.5rem)] gap-4">

      {/* Profile panel */}
      <div className="hidden md:flex w-72 flex-shrink-0 flex-col border rounded-lg p-4 gap-3">
        {/* Avatar */}
        <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center text-xl font-semibold mx-auto">
          {initials}
        </div>

        {/* ID + connection badge */}
        <div className="flex flex-col items-center gap-2">
          <p className="text-sm font-medium">{displayName}</p>
          <ConnectionStatusBadge status={connectionStatus} />
        </div>

        {/* Nút mời phỏng vấn */}
        <div className="mt-auto space-y-2">
          {connectionStatus === null && (
            <button
              onClick={() => requestMut.mutate()}
              disabled={requestMut.isPending}
              className={cn(
                "w-full text-sm px-3 py-2 rounded-md font-medium transition-colors",
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
                "w-full text-sm px-3 py-2 rounded-md font-medium transition-colors",
                "bg-primary text-primary-foreground hover:bg-primary/90",
              )}
            >
              Đặt lịch phỏng vấn
            </button>
          )}
        </div>
      </div>

      {/* Chat */}
      <div className="flex-1 border rounded-lg overflow-hidden">
        <ChatWindow
          perNeoId={per_id}
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
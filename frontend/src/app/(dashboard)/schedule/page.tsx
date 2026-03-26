'use client'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { listSchedules, updateScheduleStatus, rescheduleAppointment } from '@/lib/api/schedule'
import { getPersonnelProfile } from '@/lib/api/interview'
import { useAuthStore } from '@/store/auth.store'
import { formatDate } from '@/lib/utils'
import { cn } from '@/lib/utils'
import { buttonVariants } from '@/lib/variants'
import { PageSkeleton } from '@/components/shared/PageSkeleton'
import { ErrorState } from '@/components/shared/ErrorState'
import { useState } from 'react'
import type { ScheduleRecord } from '@/types'
import RescheduleModal from '@/components/scheduling/RescheduleModal'

const STATUS_LABEL: Record<string, string> = {
  pending:     'Chờ xác nhận',
  confirmed:   'Đã xác nhận',
  rescheduled: 'Đề xuất đổi giờ',
  cancelled:   'Đã hủy',
  completed:   'Đã hoàn thành',
}

const STATUS_COLOR: Record<string, string> = {
  pending:     'bg-amber-100 text-amber-700',
  confirmed:   'bg-green-100 text-green-700',
  rescheduled: 'bg-blue-100 text-blue-700',
  cancelled:   'bg-gray-100 text-gray-500',
  completed:   'bg-gray-100 text-gray-600',
}

export default function SchedulePage() {
  const role    = useAuthStore(s => s.role)
  const qc      = useQueryClient()
  const [rescheduleId,    setRescheduleId]    = useState<string | null>(null)
  const [expandedSummary, setExpandedSummary] = useState<string | null>(null)

  const { data: schedules = [], isLoading, error, refetch } = useQuery({
    queryKey: ['schedules'],
    queryFn:  listSchedules,
  })

  const { mutate: updateStatus } = useMutation({
    mutationFn: ({ id, status }: { id: string; status: 'confirmed' | 'cancelled' }) =>
      updateScheduleStatus(id, status),
    onSuccess: () => {
      toast.success('Đã cập nhật lịch hẹn')
      qc.invalidateQueries({ queryKey: ['schedules'] })
    },
    onError: () => toast.error('Cập nhật thất bại'),
  })

  // Fetch personnel names for org users (batch, deduped by React Query)
  const perIds = role === 'organization'
    ? [...new Set((schedules as ScheduleRecord[]).map(s => s.per_neo4j_id))]
    : []

  const profileResults = useQueries({
    queries: perIds.map(id => ({
      queryKey: ['personnel-profile', id] as const,
      queryFn:  () => getPersonnelProfile(id),
      staleTime: 5 * 60 * 1000,
    })),
  })

  const nameMap: Record<string, string> = {}
  perIds.forEach((id, i) => {
    const name = profileResults[i]?.data?.name
    if (name) nameMap[id] = name
  })

  if (isLoading) return <PageSkeleton variant="table" />
  if (error)     return <ErrorState message="Không tải được lịch hẹn" onRetry={refetch} />

  function getCounterpartLabel(s: ScheduleRecord): string {
    if (role === 'organization') return nameMap[s.per_neo4j_id] ?? s.per_neo4j_id
    return s.org_neo4j_id
  }

  return (
    <div className="max-w-3xl mx-auto py-8 px-4">
      <h1 className="text-xl font-semibold mb-6">Lịch hẹn phỏng vấn</h1>

      {schedules.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-12">
          Chưa có lịch hẹn nào
        </p>
      ) : (
        <div className="space-y-3">
          {(schedules as ScheduleRecord[]).map(s => (
            <div key={s.id} className="border rounded-lg p-4 space-y-3">

              {/* Header row */}
              <div className="flex items-start justify-between gap-3">
                <div className="space-y-1 min-w-0">

                  {/* Counterpart + email badge */}
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className="text-sm font-medium truncate">
                      {getCounterpartLabel(s)}
                    </p>
                    {s.email_sent && (
                      <span className="text-[11px] text-green-700 bg-green-50 border border-green-200 rounded px-1.5 py-0.5 shrink-0">
                        ✉ Email đã gửi
                      </span>
                    )}
                  </div>

                  {/* Date · duration · format · location */}
                  <p className="text-xs text-muted-foreground">
                    {formatDate(s.rescheduled_at ?? s.proposed_at)}
                    {' · '}{s.duration_minutes} phút
                    {' · '}{s.format === 'online' ? '🌐 Online' : '📍 Offline'}
                    {s.location ? ` · ${s.location}` : ''}
                  </p>

                  {/* Confirmed timestamp */}
                  {s.status === 'confirmed' && s.confirmed_at && (
                    <p className="text-[11px] text-green-600">
                      Xác nhận lúc: {formatDate(s.confirmed_at)}
                    </p>
                  )}
                </div>

                <span className={cn(
                  'text-xs px-2 py-1 rounded-full flex-shrink-0',
                  STATUS_COLOR[s.status] ?? 'bg-gray-100',
                )}>
                  {STATUS_LABEL[s.status] ?? s.status}
                </span>
              </div>

              {/* Chat summary (expandable) */}
              {s.chat_summary && (
                <div className="border-t pt-2">
                  <button
                    onClick={() => setExpandedSummary(expandedSummary === s.id ? null : s.id)}
                    className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1 transition-colors"
                  >
                    Tóm tắt phỏng vấn AI
                    <span>{expandedSummary === s.id ? '▲' : '▼'}</span>
                  </button>
                  {expandedSummary === s.id && (
                    <p className="mt-2 text-xs text-muted-foreground bg-muted/50 rounded-md p-3 whitespace-pre-line leading-relaxed">
                      {s.chat_summary}
                    </p>
                  )}
                </div>
              )}

              {/* Actions theo role và status */}
              <div className="flex gap-2 flex-wrap">
                {role === 'personnel' && s.status === 'pending' && (
                  <>
                    <button
                      onClick={() => updateStatus({ id: s.id, status: 'confirmed' })}
                      className={cn(buttonVariants({ variant: 'default', size: 'sm' }))}
                    >
                      Xác nhận
                    </button>
                    <button
                      onClick={() => setRescheduleId(s.id)}
                      className={cn(buttonVariants({ variant: 'outline', size: 'sm' }))}
                    >
                      Đề xuất giờ khác
                    </button>
                    <button
                      onClick={() => updateStatus({ id: s.id, status: 'cancelled' })}
                      className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'text-red-600')}
                    >
                      Từ chối
                    </button>
                  </>
                )}

                {s.status === 'rescheduled' && role === 'organization' && (
                  <>
                    <p className="text-xs text-blue-600 w-full">
                      Giờ mới đề xuất: {formatDate(s.rescheduled_at!)}
                    </p>
                    <button
                      onClick={() => updateStatus({ id: s.id, status: 'confirmed' })}
                      className={cn(buttonVariants({ variant: 'default', size: 'sm' }))}
                    >
                      Chấp nhận
                    </button>
                    <button
                      onClick={() => updateStatus({ id: s.id, status: 'cancelled' })}
                      className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'text-red-600')}
                    >
                      Hủy
                    </button>
                  </>
                )}

                {s.status !== 'cancelled' && s.status !== 'completed' && (
                  <button
                    onClick={() => updateStatus({ id: s.id, status: 'cancelled' })}
                    className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'text-red-500 ml-auto')}
                  >
                    Hủy lịch
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <RescheduleModal
        scheduleId={rescheduleId}
        open={!!rescheduleId}
        onClose={() => setRescheduleId(null)}
      />
    </div>
  )
}

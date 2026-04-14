'use client'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { listSchedules, updateScheduleStatus } from '@/lib/api/schedule'
import { getPersonnelProfile } from '@/lib/api/interview'
import { useAuthStore } from '@/store/auth.store'
import { formatDate } from '@/lib/utils'
import { cn } from '@/lib/utils'
import { buttonVariants } from '@/lib/variants'
import { PageSkeleton } from '@/components/shared/PageSkeleton'
import { ErrorState } from '@/components/shared/ErrorState'
import { useState } from 'react'
import type { ScheduleHistoryEntry, ScheduleRecord } from '@/types'

const STATUS_LABEL: Record<string, string> = {
  pending: 'Chờ xác nhận',
  confirmed: 'Đã xác nhận',
  rescheduled: 'Chờ phản hồi',
  awaiting_org_response: 'Chờ Org phản hồi',
  awaiting_personnel_response: 'Chờ ứng viên phản hồi',
  cancelled: 'Đã hủy',
  completed: 'Đã hoàn thành',
}

const STATUS_COLOR: Record<string, string> = {
  pending: 'bg-amber-100 text-amber-700',
  confirmed: 'bg-green-100 text-green-700',
  rescheduled: 'bg-blue-100 text-blue-700',
  awaiting_org_response: 'bg-blue-100 text-blue-700',
  awaiting_personnel_response: 'bg-blue-100 text-blue-700',
  cancelled: 'bg-gray-100 text-gray-500',
  completed: 'bg-gray-100 text-gray-600',
}

function getHistoryEntries(schedule: ScheduleRecord): ScheduleHistoryEntry[] {
  return Array.isArray(schedule.reschedule_history) ? schedule.reschedule_history : []
}

function describeHistoryEntry(entry: ScheduleHistoryEntry): string {
  const byLabel = entry.by === 'org' ? 'Org' : 'Ứng viên'
  return `${byLabel} đề xuất ${formatDate(entry.proposed_time)}${entry.notes ? ` · ${entry.notes}` : ''}`
}

export default function SchedulePage() {
  const role = useAuthStore((s) => s.role)
  const qc = useQueryClient()
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

  function getPendingProposalText(s: ScheduleRecord): string | null {
    const proposedAt = s.rescheduled_at ?? s.proposed_at
    if (s.status === 'awaiting_org_response' || s.status === 'rescheduled') {
      return `Ứng viên đề xuất đổi sang: ${formatDate(proposedAt)}`
    }
    if (s.status === 'awaiting_personnel_response') {
      return `Org đề xuất giờ mới: ${formatDate(proposedAt)}`
    }
    return null
  }

  function renderHistory(s: ScheduleRecord) {
    const history = getHistoryEntries(s)
    if (history.length === 0) return null

    return (
      <div className="border-t pt-2">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Lịch sử đổi lịch
        </p>
        <div className="mt-2 space-y-2">
          {history.slice(-4).map((entry, index) => (
            <div key={`${entry.timestamp}-${index}`} className="rounded-md bg-muted/40 px-3 py-2 text-xs leading-5">
              <p className="font-medium text-foreground">{describeHistoryEntry(entry)}</p>
              <p className="text-muted-foreground">{formatDate(entry.timestamp)}</p>
            </div>
          ))}
        </div>
      </div>
    )
  }

  const awaitingOrg = (s: ScheduleRecord) => s.status === 'awaiting_org_response' || s.status === 'rescheduled'
  const awaitingPersonnel = (s: ScheduleRecord) => s.status === 'awaiting_personnel_response'

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <h1 className="mb-6 text-2xl font-bold tracking-tight">Lịch hẹn phỏng vấn</h1>

      {schedules.length === 0 ? (
        <p className="py-12 text-center text-sm text-muted-foreground">
          Chưa có lịch hẹn nào
        </p>
      ) : (
        <div className="space-y-3.5">
          {(schedules as ScheduleRecord[]).map(s => (
            <div key={s.id} className="space-y-3 rounded-2xl border border-border/70 bg-card/90 p-4 shadow-sm">

              {/* Header row */}
              <div className="flex items-start justify-between gap-3">
                <div className="space-y-1 min-w-0">

                  {/* Counterpart + email badge */}
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className="text-sm font-medium truncate">
                      {getCounterpartLabel(s)}
                    </p>
                    {s.email_sent && (
                      <span className="shrink-0 rounded-md border border-green-300/60 bg-green-100/60 px-1.5 py-0.5 text-[11px] text-green-700">
                        ✉ Email đã gửi
                      </span>
                    )}
                  </div>

                  {/* Date · duration · format · location */}
                  <p className="text-xs text-muted-foreground">
                    {formatDate(s.rescheduled_at ?? s.proposed_at)}
                    {' · '}{s.duration_minutes} phút
                    {' · '}{s.format === 'online' ? ' Online' : ' Offline'}
                    {s.location ? ` · ${s.location}` : ''}
                  </p>

                  {/* Confirmed timestamp */}
                  {s.status === 'confirmed' && s.confirmed_at && (
                    <p className="text-[11px] font-medium text-green-600">
                      Xác nhận lúc: {formatDate(s.confirmed_at)}
                    </p>
                  )}
                </div>

                <span className={cn(
                  'flex-shrink-0 rounded-full px-2 py-1 text-xs font-medium',
                  STATUS_COLOR[s.status] ?? 'bg-gray-100',
                )}>
                  {STATUS_LABEL[s.status] ?? s.status}
                </span>
              </div>

              {getPendingProposalText(s) ? (
                <div className="rounded-xl border border-blue-300/60 bg-blue-100/55 px-3 py-2 text-xs text-blue-800">
                  {getPendingProposalText(s)}
                </div>
              ) : null}

              {/* Chat summary (expandable) */}
              {s.chat_summary && (
                <div className="border-t border-border/70 pt-2">
                  <button
                    onClick={() => setExpandedSummary(expandedSummary === s.id ? null : s.id)}
                    className="flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
                  >
                    Tóm tắt phỏng vấn AI
                    <span>{expandedSummary === s.id ? '▲' : '▼'}</span>
                  </button>
                  {expandedSummary === s.id && (
                    <p className="mt-2 whitespace-pre-line rounded-xl bg-muted/45 p-3 text-xs leading-relaxed text-muted-foreground">
                      {s.chat_summary}
                    </p>
                  )}
                </div>
              )}

              {renderHistory(s)}

              {/* Actions theo role và status */}
              <div className="flex gap-2 flex-wrap">
                {role === 'personnel' && (s.status === 'pending' || awaitingPersonnel(s)) && (
                  <>
                    <button
                      onClick={() => updateStatus({ id: s.id, status: 'confirmed' })}
                      className={cn(buttonVariants({ variant: 'default', size: 'sm' }))}
                    >
                      Xác nhận
                    </button>
                    <button
                      onClick={() => updateStatus({ id: s.id, status: 'cancelled' })}
                      className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'text-red-600')}
                    >
                      Từ chối
                    </button>
                  </>
                )}

                {role === 'organization' && awaitingOrg(s) && (
                  <>
                    <p className="text-xs text-blue-600 w-full">
                      Giờ mới đề xuất: {formatDate(s.rescheduled_at ?? s.proposed_at)}
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

    </div>
  )
}

'use client'
import { useQuery } from '@tanstack/react-query'
import { getAvailableSlots } from '@/lib/api/schedule'
import { formatDate } from '@/lib/utils'
import { cn } from '@/lib/utils'
import type { AvailableSlot } from '@/types'
import { PageSkeleton } from '@/components/shared/PageSkeleton'

interface SlotCalendarProps {
  perNeoId:       string
  selectedSlot:   AvailableSlot | null
  onSelectSlot:   (slot: AvailableSlot) => void
}

export default function SlotCalendar({
  perNeoId, selectedSlot, onSelectSlot,
}: SlotCalendarProps) {
  const { data: slots = [], isLoading, error } = useQuery({
    queryKey: ['slots', perNeoId],
    queryFn:  () => getAvailableSlots(perNeoId),
    staleTime: 60_000,
  })

  if (isLoading) return <PageSkeleton variant="form" />
  if (error)     return <p className="text-sm font-medium text-red-500">Không thể tải lịch</p>
  if (!slots.length) return (
    <p className="py-8 text-center text-sm text-muted-foreground">
      Ứng viên chưa thiết lập lịch rảnh
    </p>
  )

  // Group slots theo ngày
  const grouped = slots.reduce<Record<string, AvailableSlot[]>>((acc, slot) => {
    const date = slot.start.slice(0, 10)
    if (!acc[date]) acc[date] = []
    acc[date].push(slot)
    return acc
  }, {})

  return (
    <div className="max-h-80 space-y-4 overflow-y-auto pr-1">
      {Object.entries(grouped).map(([date, daySlots]) => (
        <div key={date}>
          <p className="mb-2 text-xs font-semibold text-muted-foreground">
            {new Date(date).toLocaleDateString('vi-VN', {
              weekday: 'long', day: '2-digit', month: '2-digit',
            })}
          </p>
          <div className="flex flex-wrap gap-2">
            {daySlots.map(slot => {
              const isSelected = selectedSlot?.start === slot.start
              return (
                <button
                  key={slot.start}
                  onClick={() => onSelectSlot(slot)}
                  className={cn(
                    'rounded-xl border px-3 py-1.5 text-xs font-medium transition-all duration-200',
                    isSelected
                      ? 'border-primary bg-primary text-primary-foreground shadow-sm'
                      : 'border-border/80 bg-card/80 hover:border-primary/60 hover:text-primary',
                  )}
                >
                  {new Date(slot.start).toLocaleTimeString('vi-VN', {
                    hour: '2-digit', minute: '2-digit',
                  })}
                </button>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
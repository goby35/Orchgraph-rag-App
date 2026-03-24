'use client'
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { rescheduleAppointment } from '@/lib/api/schedule'
import { cn } from '@/lib/utils'
import { buttonVariants } from '@/lib/variants'

interface RescheduleModalProps {
  scheduleId: string | null
  open:       boolean
  onClose:    () => void
}

export default function RescheduleModal({ scheduleId, open, onClose }: RescheduleModalProps) {
  const [datetime, setDatetime] = useState('')
  const [notes,    setNotes]    = useState('')
  const qc = useQueryClient()

  const { mutate, isPending } = useMutation({
    mutationFn: () => rescheduleAppointment(scheduleId!, datetime, notes || undefined),
    onSuccess: () => {
      toast.success('Đã đề xuất giờ mới')
      qc.invalidateQueries({ queryKey: ['schedules'] })
      onClose()
    },
    onError: () => toast.error('Thất bại — thử lại'),
  })

  if (!open) return null

  return (
    <div
      className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="bg-background rounded-xl border shadow-lg w-full max-w-sm p-4 space-y-4">
        <h2 className="font-semibold">Đề xuất giờ mới</h2>

        <div className="space-y-2">
          <label className="text-sm text-muted-foreground">Thời gian mới</label>
          <input
            type="datetime-local"
            value={datetime}
            onChange={e => setDatetime(e.target.value)}
            className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
          />
        </div>

        <div className="space-y-2">
          <label className="text-sm text-muted-foreground">Ghi chú (không bắt buộc)</label>
          <textarea
            value={notes}
            onChange={e => setNotes(e.target.value)}
            rows={2}
            className="w-full border rounded-lg px-3 py-2 text-sm bg-background resize-none"
          />
        </div>

        <div className="flex gap-2">
          <button
            onClick={onClose}
            className={cn(buttonVariants({ variant: 'outline' }), 'flex-1')}
          >
            Hủy
          </button>
          <button
            onClick={() => mutate()}
            disabled={!datetime || isPending}
            className={cn(buttonVariants({ variant: 'default' }), 'flex-1')}
          >
            {isPending ? 'Đang gửi...' : 'Đề xuất'}
          </button>
        </div>
      </div>
    </div>
  )
}
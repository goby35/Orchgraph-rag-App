'use client'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { buttonVariants } from '@/lib/variants'

interface RescheduleModalProps {
  scheduleId: string | null
  open:       boolean
  onClose:    () => void
  title?:     string
  description?: string
  confirmLabel?: string
  onSubmit:   (proposedTime: string, notes?: string) => Promise<void>
}

export default function RescheduleModal({
  scheduleId,
  open,
  onClose,
  title = 'Đề xuất giờ mới',
  description,
  confirmLabel = 'Đề xuất',
  onSubmit,
}: RescheduleModalProps) {
  const [datetime, setDatetime] = useState('')
  const [notes,    setNotes]    = useState('')
  const [isPending, setIsPending] = useState(false)

  useEffect(() => {
    if (!open) return
    setDatetime('')
    setNotes('')
    setIsPending(false)
  }, [open, scheduleId])

  if (!open) return null

  const handleSubmit = async () => {
    if (!scheduleId || !datetime) return
    setIsPending(true)
    try {
      await onSubmit(datetime, notes || undefined)
      toast.success('Đã gửi đề xuất')
      onClose()
    } catch {
      toast.error('Thất bại — thử lại')
    } finally {
      setIsPending(false)
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="bg-background rounded-xl border shadow-lg w-full max-w-sm p-4 space-y-4">
        <h2 className="font-semibold">{title}</h2>
        {description ? (
          <p className="text-xs text-muted-foreground leading-5">{description}</p>
        ) : null}

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
            onClick={() => { void handleSubmit() }}
            disabled={!datetime || isPending}
            className={cn(buttonVariants({ variant: 'default' }), 'flex-1')}
          >
            {isPending ? 'Đang gửi...' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
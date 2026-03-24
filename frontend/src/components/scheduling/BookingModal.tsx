'use client'
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { createSchedule } from '@/lib/api/schedule'
import SlotCalendar from './SlotCalendar'
import { cn } from '@/lib/utils'
import { buttonVariants } from '@/lib/variants'
import type { AvailableSlot } from '@/types'

interface BookingModalProps {
  perNeoId: string
  open:     boolean
  onClose:  () => void
}

type Step = 'select' | 'confirm' | 'success'

export default function BookingModal({ perNeoId, open, onClose }: BookingModalProps) {
  const [step,         setStep]         = useState<Step>('select')
  const [selectedSlot, setSelectedSlot] = useState<AvailableSlot | null>(null)
  const [format,       setFormat]       = useState<'online' | 'offline'>('online')
  const [location,     setLocation]     = useState('')
  const [notes,        setNotes]        = useState('')

  const queryClient = useQueryClient()

  const { mutate: book, isPending } = useMutation({
    mutationFn: () => createSchedule({
      per_neo4j_id:     perNeoId,
      proposed_at:      selectedSlot!.start,
      duration_minutes: selectedSlot!.duration,
      format,
      location:         location || undefined,
      notes:            notes    || undefined,
    }),
    onSuccess: () => {
      setStep('success')
      queryClient.invalidateQueries({ queryKey: ['schedules'] })
    },
    onError: () => toast.error('Đặt lịch thất bại — thử lại'),
  })

  const handleClose = () => {
    setStep('select')
    setSelectedSlot(null)
    setNotes('')
    setLocation('')
    onClose()
  }

  if (!open) return null

  return (
    // Overlay
    <div
      className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
      onClick={e => { if (e.target === e.currentTarget) handleClose() }}
    >
      <div className="bg-background rounded-xl border shadow-lg w-full max-w-md">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b">
          <h2 className="font-semibold">
            {step === 'select'  && 'Chọn thời gian'}
            {step === 'confirm' && 'Xác nhận lịch hẹn'}
            {step === 'success' && 'Đặt lịch thành công'}
          </h2>
          <button onClick={handleClose} className="text-muted-foreground hover:text-foreground">✕</button>
        </div>

        <div className="p-4">
          {/* Step 1: chọn slot */}
          {step === 'select' && (
            <>
              <SlotCalendar
                perNeoId={perNeoId}
                selectedSlot={selectedSlot}
                onSelectSlot={setSelectedSlot}
              />
              <button
                onClick={() => setStep('confirm')}
                disabled={!selectedSlot}
                className={cn(buttonVariants({ variant: 'default' }), 'w-full mt-4')}
              >
                Tiếp theo
              </button>
            </>
          )}

          {/* Step 2: confirm */}
          {step === 'confirm' && selectedSlot && (
            <div className="space-y-4">
              <div className="bg-muted rounded-lg p-3 text-sm space-y-1">
                <p><span className="text-muted-foreground">Thời gian:</span>{' '}
                  {new Date(selectedSlot.start).toLocaleString('vi-VN')}
                </p>
                <p><span className="text-muted-foreground">Thời lượng:</span>{' '}
                  {selectedSlot.duration} phút
                </p>
              </div>

              {/* Format */}
              <div className="flex gap-2">
                {(['online', 'offline'] as const).map(f => (
                  <button
                    key={f}
                    onClick={() => setFormat(f)}
                    className={cn(
                      'flex-1 py-2 text-sm rounded-lg border transition-colors',
                      format === f && 'bg-primary text-primary-foreground border-primary',
                    )}
                  >
                    {f === 'online' ? 'Online' : 'Tại văn phòng'}
                  </button>
                ))}
              </div>

              {/* Location */}
              <input
                type="text"
                value={location}
                onChange={e => setLocation(e.target.value)}
                placeholder={format === 'online' ? 'Link Google Meet...' : 'Địa chỉ văn phòng...'}
                className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
              />

              {/* Notes */}
              <textarea
                value={notes}
                onChange={e => setNotes(e.target.value)}
                placeholder="Ghi chú thêm (không bắt buộc)..."
                rows={2}
                className="w-full border rounded-lg px-3 py-2 text-sm bg-background resize-none"
              />

              <div className="flex gap-2">
                <button
                  onClick={() => setStep('select')}
                  className={cn(buttonVariants({ variant: 'outline' }), 'flex-1')}
                >
                  Quay lại
                </button>
                <button
                  onClick={() => book()}
                  disabled={isPending}
                  className={cn(buttonVariants({ variant: 'default' }), 'flex-1')}
                >
                  {isPending ? 'Đang xử lý...' : 'Xác nhận'}
                </button>
              </div>
            </div>
          )}

          {/* Step 3: success */}
          {step === 'success' && (
            <div className="text-center py-4 space-y-3">
              <div className="w-12 h-12 rounded-full bg-green-100 flex items-center justify-center mx-auto">
                <svg className="w-6 h-6 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <p className="font-medium">Đặt lịch thành công!</p>
              <p className="text-sm text-muted-foreground">
                Email xác nhận đã được gửi đến ứng viên.
              </p>
              <button
                onClick={handleClose}
                className={cn(buttonVariants({ variant: 'default' }), 'w-full')}
              >
                Đóng
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
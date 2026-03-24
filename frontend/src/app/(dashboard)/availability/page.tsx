'use client'
import { useState, useEffect } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import WeeklySlotPicker from '@/components/scheduling/WeeklySlotPicker'
import { buttonVariants } from '@/lib/variants'
import { cn } from '@/lib/utils'
import { upsertAvailability } from '@/lib/api/schedule'
import { apiClient } from '@/lib/api/client'

  type WeeklySlots = Record<string, [string, string] | null>

const DEFAULT_SLOTS: WeeklySlots = {
  Mon: ['09:00', '18:00'],
  Tue: ['09:00', '18:00'],
  Wed: ['09:00', '18:00'],
  Thu: ['09:00', '18:00'],
  Fri: ['09:00', '18:00'],
  Sat: null,
  Sun: null,
}

export default function AvailabilityPage() {
  const [slots, setSlots] = useState<WeeklySlots>(DEFAULT_SLOTS)

  // Load giá trị hiện tại
  // const { data: existing } = useQuery({
  //   queryKey: ['availability', 'me'],
  //   queryFn:  () => apiClient.get('/availability/me').then(r => r.data).catch(() => null),
  // })

  // useEffect(() => {
  //   if (existing?.weekly_slots) {
  //     setSlots(existing.weekly_slots)
  //   }
  // }, [existing])

  const { mutate: save, isPending } = useMutation({
    mutationFn: () => {
      const cleanSlots = Object.fromEntries(
        Object.entries(slots).filter(
        (entry): entry is [string, [string, string]] => entry[1] !== null && entry[1] !== undefined
        )
      )
      return upsertAvailability({
      weekly_slots:          cleanSlots,
      timezone:              'Asia/Ho_Chi_Minh',
      advance_notice_hours:  24,
      slot_duration_minutes: 60,
    })
  },
    onSuccess: () => toast.success('Đã lưu lịch rảnh'),
    onError:   () => toast.error('Lưu thất bại — thử lại'),
  })

  return (
    <div className="max-w-lg mx-auto py-8 px-4">
      <h1 className="text-xl font-semibold mb-1">Lịch rảnh của bạn</h1>
      <p className="text-sm text-muted-foreground mb-6">
        Tổ chức sẽ chọn giờ phỏng vấn từ khung giờ này.
      </p>

      <WeeklySlotPicker value={slots} onChange={(slots) => setSlots(slots as WeeklySlots)} />

      <button
        onClick={() => save()}
        disabled={isPending}
        className={cn(buttonVariants({ variant: 'default' }), 'w-full mt-6')}
      >
        {isPending ? 'Đang lưu...' : 'Lưu lịch rảnh'}
      </button>
    </div>
  )
}
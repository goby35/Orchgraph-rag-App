'use client'
import { useState } from 'react'
import { cn } from '@/lib/utils'
import { buttonVariants } from '@/lib/variants'

// weekly_slots format: { Mon: ["09:00", "18:00"] | null, ... }
type DayKey = 'Mon' | 'Tue' | 'Wed' | 'Thu' | 'Fri' | 'Sat' | 'Sun'
type WeeklySlots = Partial<Record<DayKey, [string, string] | null>>

const DAY_LABELS: Record<DayKey, string> = {
  Mon: 'Thứ 2', Tue: 'Thứ 3', Wed: 'Thứ 4',
  Thu: 'Thứ 5', Fri: 'Thứ 6', Sat: 'Thứ 7', Sun: 'CN',
}
const DAYS = Object.keys(DAY_LABELS) as DayKey[]

interface WeeklySlotPickerProps {
  value:    WeeklySlots
  onChange: (slots: WeeklySlots) => void
}

export default function WeeklySlotPicker({ value, onChange }: WeeklySlotPickerProps) {
  const toggle = (day: DayKey) => {
    const next = { ...value }
    if (next[day]) {
      next[day] = null
    } else {
      next[day] = ['09:00', '18:00']
    }
    onChange(next)
  }

  const updateTime = (day: DayKey, idx: 0 | 1, time: string) => {
    const current = value[day]
    if (!current) return
    const updated: [string, string] = [...current] as [string, string]
    updated[idx] = time
    onChange({ ...value, [day]: updated })
  }

  return (
    <div className="space-y-2.5">
      {DAYS.map(day => {
        const slot   = value[day]
        const active = !!slot

        return (
          <div key={day} className={cn(
            'flex items-center gap-3 rounded-xl border border-border/70 p-3 transition-all duration-200',
            active ? 'bg-card/90 shadow-sm' : 'bg-muted/35',
          )}>
            {/* Toggle checkbox */}
            <button
              type="button"
              onClick={() => toggle(day)}
              className={cn(
                'h-5 w-5 flex-shrink-0 rounded border-2 transition-colors',
                active
                  ? 'bg-primary border-primary'
                  : 'border-muted-foreground',
              )}
            >
              {active && (
                <svg viewBox="0 0 12 12" className="w-full h-full text-primary-foreground p-0.5">
                  <path d="M2 6l3 3 5-5" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round"/>
                </svg>
              )}
            </button>

            {/* Day label */}
            <span className={cn(
              'w-12 text-sm font-medium flex-shrink-0',
              !active && 'text-muted-foreground',
            )}>
              {DAY_LABELS[day]}
            </span>

            {/* Time inputs */}
            {active && slot ? (
              <div className="flex items-center gap-2 flex-1">
                <input
                  type="time"
                  value={slot[0]}
                  onChange={e => updateTime(day, 0, e.target.value)}
                  className="rounded-lg border border-input/80 bg-background/90 px-2 py-1 text-sm"
                />
                <span className="text-muted-foreground text-sm">—</span>
                <input
                  type="time"
                  value={slot[1]}
                  onChange={e => updateTime(day, 1, e.target.value)}
                  className="rounded-lg border border-input/80 bg-background/90 px-2 py-1 text-sm"
                />
              </div>
            ) : (
              <span className="text-sm text-muted-foreground">Nghỉ</span>
            )}
          </div>
        )
      })}
    </div>
  )
}
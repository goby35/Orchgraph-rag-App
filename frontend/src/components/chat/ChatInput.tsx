'use client'
import { useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { buttonVariants } from '@/lib/variants'

interface ChatInputProps {
  onSend:   (text: string) => void
  disabled: boolean
}

export default function ChatInput({ onSend, disabled }: ChatInputProps) {
  const [text, setText] = useState('')
  const ref  = useRef<HTMLTextAreaElement>(null)

  const handleSend = () => {
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setText('')
    // Reset height
    if (ref.current) ref.current.style.height = 'auto'
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value)
    // Auto-resize
    if (ref.current) {
      ref.current.style.height = 'auto'
      ref.current.style.height = `${ref.current.scrollHeight}px`
    }
  }

  return (
    <div className="flex gap-2 items-end border-t p-3">
      <textarea
        ref={ref}
        value={text}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder="Nhập câu hỏi cho Digital Twin... (Enter để gửi)"
        rows={1}
        className={cn(
          'flex-1 resize-none rounded-lg border bg-background px-3 py-2',
          'text-sm focus:outline-none focus:ring-2 focus:ring-ring',
          'max-h-32 overflow-y-auto disabled:opacity-50',
        )}
      />
      <button
        onClick={handleSend}
        disabled={disabled || !text.trim()}
        className={cn(
          buttonVariants({ variant: 'default', size: 'sm' }),
          'flex-shrink-0',
        )}
      >
        Gửi
      </button>
    </div>
  )
}
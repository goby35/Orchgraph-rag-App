'use client'
import { useEffect, useRef } from 'react'
import { useAuthStore } from '@/store/auth.store'
import { useDigitalTwinChat } from '@/hooks/useDigitalTwinChat'
import ChatBubble from './ChatBubble'
import ChatInput  from './ChatInput'
import { cn } from '@/lib/utils'
import { PageSkeleton } from '@/components/shared/PageSkeleton'

interface ChatWindowProps {
  perNeoId:          string
  onBookInterview?:  () => void
}

export default function ChatWindow({ perNeoId, onBookInterview }: ChatWindowProps) {
  const neoId  = useAuthStore(s => s.neoId) ?? ''
  const endRef = useRef<HTMLDivElement>(null)

  const { messages, status, historyLoaded, isStreaming, send } =
    useDigitalTwinChat({ perNeoId, orgNeoId: neoId })

  // Auto-scroll khi có message mới
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <div className="flex flex-col h-full">
      {/* Status banner — chỉ hiện khi có vấn đề */}
      {status === 'connecting' && (
        <div className="px-4 py-2 text-xs text-center bg-amber-50 text-amber-700 border-b">
          Đang kết nối...
        </div>
      )}
      {status === 'error' && (
        <div className="px-4 py-2 text-xs text-center bg-red-50 text-red-700 border-b">
          Kết nối thất bại — thử gửi lại
        </div>
      )}

      {/* Message list */}
      <div className="flex-1 overflow-y-auto p-4">
        {!historyLoaded ? (
          <PageSkeleton variant="chat" />
        ) : messages.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <p className="text-sm text-muted-foreground text-center">
              Hãy đặt câu hỏi để bắt đầu phỏng vấn Digital Twin
            </p>
          </div>
        ) : (
          messages.map(msg => <ChatBubble key={msg.id} message={msg} />)
        )}
        <div ref={endRef} />
      </div>

      {/* Booking button */}
      {onBookInterview && (
        <div className="px-4 pt-2 border-t">
          <button
            onClick={onBookInterview}
            className="w-full text-sm py-2 rounded-lg border border-green-500 text-green-700 hover:bg-green-50 transition-colors"
          >
            Đặt lịch phỏng vấn thực
          </button>
        </div>
      )}

      {/* Input */}
      <ChatInput
        onSend={send}
        disabled={isStreaming || status === 'connecting'}
      />
    </div>
  )
}
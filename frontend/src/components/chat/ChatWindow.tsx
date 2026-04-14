'use client'
import { useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/store/auth.store'
import { useDigitalTwinChat } from '@/hooks/useDigitalTwinChat'
import ChatBubble from './ChatBubble'
import ChatInput  from './ChatInput'
import { PageSkeleton } from '@/components/shared/PageSkeleton'
import { SessionSidebar } from '@/components/interview/SessionSidebar'

interface ChatWindowProps {
  perNeoId:          string
  onBookInterview?:  () => void
  onSessionResolved?: (sessionId: string | null) => void
  title?:            string
  subtitle?:         string
  requestedSessionId?: string | null
  createSessionOnMount?: boolean
  initialJobTitle?: string | null
}

export default function ChatWindow({
  perNeoId,
  onBookInterview,
  onSessionResolved,
  title,
  subtitle,
  requestedSessionId,
  createSessionOnMount,
  initialJobTitle,
}: ChatWindowProps) {
  const neoId  = useAuthStore(s => s.neoId) ?? ''
  const router = useRouter()
  const endRef = useRef<HTMLDivElement>(null)

  const { messages, status, historyLoaded, isStreaming, send, sessionId } =
    useDigitalTwinChat({
      perNeoId,
      orgNeoId: neoId,
      requestedSessionId,
      createSessionOnMount,
      initialJobTitle,
    })

  // Auto-scroll khi có message mới
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    onSessionResolved?.(sessionId ?? null)
  }, [onSessionResolved, sessionId])

  const handleSessionSelect = async (session: {
    session_id: string
    personnel_id: string
    job_title: string
  }) => {
    const params = new URLSearchParams({
      sessionId: session.session_id,
      jobTitle: session.job_title || 'Vị trí chưa xác định',
    })

    router.push(`/interview/${encodeURIComponent(session.personnel_id)}?${params.toString()}`, { scroll: false })
  }

  const hasStreamingBubble = messages.some((msg) => msg.role === 'assistant' && msg.streaming)

  return (
    <div className="flex h-full min-h-0 flex-col lg:flex-row">
      <SessionSidebar
        activeSessionId={sessionId}
        currentOrgId={neoId}
        onSessionSelect={handleSessionSelect}
      />

      <div className="flex min-h-0 flex-1 flex-col">
        {(title || subtitle) && (
          <header className="border-b px-4 py-3">
            {title ? (
              <h2 className="text-base font-semibold tracking-tight md:text-lg">{title}</h2>
            ) : null}
            {subtitle ? (
              <p className="mt-0.5 text-xs text-muted-foreground md:text-sm">{subtitle}</p>
            ) : null}
          </header>
        )}

        {/* Status banner — chỉ hiện khi có vấn đề */}
        {status === 'connecting' && (
          <div className="border-b bg-amber-50 px-4 py-2 text-center text-xs text-amber-700">
            Đang kết nối...
          </div>
        )}
        {status === 'error' && (
          <div className="border-b bg-red-50 px-4 py-2 text-center text-xs text-red-700">
            Kết nối thất bại — thử gửi lại
          </div>
        )}

        {/* Message list */}
        <div className="flex-1 overflow-y-auto p-4">
          {!historyLoaded ? (
            <PageSkeleton variant="chat" />
          ) : messages.length === 0 ? (
            <div className="flex h-full items-center justify-center">
              <p className="text-center text-sm text-muted-foreground">
                Hãy đặt câu hỏi để bắt đầu phỏng vấn Digital Twin
              </p>
            </div>
          ) : (
            <>
              {messages.map(msg => <ChatBubble key={msg.id} message={msg} />)}
              {isStreaming && !hasStreamingBubble ? (
                <div className="mb-4 flex gap-3">
                  <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full border bg-muted text-xs font-semibold text-muted-foreground">
                    AI
                  </div>
                  <div className="rounded-2xl rounded-tl-sm bg-muted px-4 py-2.5">
                    <div className="flex items-center gap-1">
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-foreground/70 [animation-delay:-0.2s]" />
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-foreground/70 [animation-delay:-0.1s]" />
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-foreground/70" />
                    </div>
                  </div>
                </div>
              ) : null}
            </>
          )}
          <div ref={endRef} />
        </div>

        {/* Booking button */}
        {onBookInterview && (
          <div className="border-t px-4 pt-2">
            <button
              onClick={onBookInterview}
              className="w-full rounded-lg border border-green-500 py-2 text-sm text-green-700 transition-colors hover:bg-green-50"
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
    </div>
  )
}
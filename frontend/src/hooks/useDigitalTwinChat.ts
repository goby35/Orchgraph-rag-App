'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import { getChatHistory, saveChatMessage } from '@/lib/api/interview'
import type { ChatMessage, ChatHistoryItem, WsStatus, WsChunk } from '@/types'

interface Options {
  perNeoId: string
  orgNeoId: string
}

export function useDigitalTwinChat({ perNeoId, orgNeoId }: Options) {
  const wsRef                = useRef<WebSocket | null>(null)
  // Accumulates assistant chunks so we can persist the full response on 'done'
  const assistantContentRef  = useRef<string>('')
  const [messages,      setMessages]      = useState<ChatMessage[]>([])
  const [status,        setStatus]        = useState<WsStatus>('open')
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [isStreaming,   setIsStreaming]   = useState(false)

  // Load lịch sử khi mount
  useEffect(() => {
    getChatHistory(perNeoId)
      .then((history: unknown) => {
        const items = Array.isArray(history)
          ? history
          : ((history as { messages?: ChatHistoryItem[] })?.messages ?? [])

        setMessages(
          (items as ChatHistoryItem[]).map(h => ({
            id:      h.id ?? crypto.randomUUID(),
            role:    h.role,
            content: h.content,
          }))
        )
      })
      .catch(() => {})
      .finally(() => setHistoryLoaded(true))
  }, [perNeoId])

  const send = useCallback(async (question: string) => {
    if (isStreaming) return

    const supabase = createClient()
    const { data: { session } } = await supabase.auth.getSession()
    if (!session?.access_token) return

    // Reset accumulator for this turn
    assistantContentRef.current = ''

    // 1. Optimistic update — hiện message user ngay
    const userMsg: ChatMessage = {
      id:      crypto.randomUUID(),
      role:    'user',
      content: question,
    }
    setMessages(prev => [...prev, userMsg])
    setIsStreaming(true)
    setStatus('connecting')

    // 2. Mở WS mới cho mỗi câu hỏi
    const wsUrl = `${process.env.NEXT_PUBLIC_WS_URL}/interview/ws`
    const ws    = new WebSocket(wsUrl)
    wsRef.current = ws

    const assistantId = crypto.randomUUID()

    ws.onopen = () => {
      setStatus('open')
      ws.send(JSON.stringify({
        token:        session.access_token,
        personnel_id: perNeoId,
        question,
      }))
    }

    ws.onmessage = (event) => {
      let data: WsChunk
      try {
        data = JSON.parse(event.data as string) as WsChunk
      } catch {
        return
      }

      if ('chunk' in data) {
        // Track full assistant content for persistence
        assistantContentRef.current += data.chunk

        setMessages(prev => {
          const last = prev[prev.length - 1]
          if (last?.streaming && last.id === assistantId) {
            return [
              ...prev.slice(0, -1),
              { ...last, content: last.content + data.chunk },
            ]
          }
          return [...prev, {
            id:        assistantId,
            role:      'assistant' as const,
            content:   (data as { chunk: string }).chunk,
            streaming: true,
          }]
        })
      }

      if ('done' in data) {
        const assistantContent  = assistantContentRef.current
        const isPrivate         = data.is_private_mode
        assistantContentRef.current = ''

        setMessages(prev => prev.map(m =>
          m.id === assistantId ? { ...m, streaming: false } : m
        ))
        setIsStreaming(false)
        setStatus('open')

        // Persist user message
        saveChatMessage({
          per_neo4j_id:    perNeoId,
          role:            'user',
          content:         question,
          is_private_mode: false,
        }).catch(() => {})

        // Persist assistant response (the missing piece)
        if (assistantContent) {
          saveChatMessage({
            per_neo4j_id:    perNeoId,
            role:            'assistant',
            content:         assistantContent,
            is_private_mode: isPrivate,
          }).catch(() => {})
        }
      }

      if ('error' in data) {
        assistantContentRef.current = ''
        setMessages(prev => [...prev, {
          id:      crypto.randomUUID(),
          role:    'assistant' as const,
          content: `Lỗi: ${(data as { error: string }).error}`,
        }])
        setIsStreaming(false)
        setStatus('error')
      }
    }

    ws.onerror = () => {
      assistantContentRef.current = ''
      setStatus('error')
      setIsStreaming(false)
      setMessages(prev => [...prev, {
        id:      crypto.randomUUID(),
        role:    'assistant' as const,
        content: 'Không thể kết nối. Vui lòng thử lại.',
      }])
    }

    ws.onclose = () => {
      if (status !== 'error') setStatus('open')
    }

  }, [perNeoId, isStreaming, status])

  return { messages, status, historyLoaded, isStreaming, send }
}

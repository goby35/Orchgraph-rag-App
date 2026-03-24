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
  const wsRef           = useRef<WebSocket | null>(null)
  const [messages,      setMessages]      = useState<ChatMessage[]>([])
  const [status,        setStatus]        = useState<WsStatus>('open') // open by default vì không persistent
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
      // Gửi token + câu hỏi trong message đầu tiên
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
        // Append chunk vào assistant message
        setMessages(prev => {
          const last = prev[prev.length - 1]
          if (last?.streaming && last.id === assistantId) {
            return [
              ...prev.slice(0, -1),
              { ...last, content: last.content + data.chunk },
            ]
          }
          // Tạo assistant message mới
          return [...prev, {
            id:        assistantId,
            role:      'assistant' as const,
            content:   (data as { chunk: string }).chunk,
            streaming: true,
          }]
        })
      }

      if ('done' in data) {
        // Kết thúc stream
        setMessages(prev => prev.map(m =>
          m.id === assistantId ? { ...m, streaming: false } : m
        ))
        setIsStreaming(false)
        setStatus('open')

        // Lưu message user + assistant vào backend (fire-and-forget)
        saveChatMessage({
          per_neo4j_id:    perNeoId,
          role:            'user',
          content:         question,
          is_private_mode: false,
        }).catch(() => {})
      }

      if ('error' in data) {
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
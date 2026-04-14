'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import {
  createInterviewSession,
  getInterviewHistory,
  getInterviewSessions,
  saveInterviewMessage,
} from '@/lib/api/chat'
import type { ChatMessage, ChatHistoryItem, WsStatus, WsChunk } from '@/types'

interface Options {
  perNeoId: string
  orgNeoId: string
  requestedSessionId?: string | null
  sessionId?: string | null
  createSessionOnMount?: boolean
  initialJobTitle?: string | null
}

function formatAssistantText(raw: string): string {
  if (!raw) return ""

  let text = raw
    .replace(/^\s*STATE\s*:\s*FOUND\s*ANSWER\s*:\s*/i, "")
    .replace(/^\s*FOUND\s*ANSWER\s*:\s*/i, "")
    .replace(/^\s*ANSWER\s*:\s*/i, "")

  // UI chưa render markdown nên strip marker để tránh lộ **text**.
  text = text.replace(/\*\*(.*?)\*\*/g, "$1").replace(/__(.*?)__/g, "$1")

  // Tách bullet thành dòng riêng nếu model trả về inline list.
  text = text.replace(/\s+-\s+/g, "\n- ")

  return text.replace(/\n{3,}/g, "\n\n").trim()
}

export function useDigitalTwinChat({
  perNeoId,
  orgNeoId,
  requestedSessionId,
  sessionId: externalSessionId,
  createSessionOnMount = false,
  initialJobTitle,
}: Options) {
  const wsRef                = useRef<WebSocket | null>(null)
  // Accumulates assistant chunks so we can persist the full response on 'done'
  const assistantContentRef  = useRef<string>('')
  const sessionIdRef         = useRef<string | null>(null)
  const creatingSessionRef   = useRef<Promise<string> | null>(null)
  const localStorageKey      = `dt_chat_session:${orgNeoId}:${perNeoId}`
  const transcriptStorageKey = `${localStorageKey}:messages`
  const [messages,      setMessages]      = useState<ChatMessage[]>([])
  const [status,        setStatus]        = useState<WsStatus>('open')
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [isStreaming,   setIsStreaming]   = useState(false)
  const [currentSessionId, setSessionId]   = useState<string | null>(null)
  const activeSessionId = (externalSessionId ?? requestedSessionId ?? null)?.trim() || null

  useEffect(() => {
    sessionIdRef.current = currentSessionId
  }, [currentSessionId])

  useEffect(() => {
    const currentSessionId = sessionIdRef.current
    if (!currentSessionId) return

    localStorage.setItem(
      transcriptStorageKey,
      JSON.stringify({ sessionId: currentSessionId, messages }),
    )
  }, [messages, transcriptStorageKey])

  const ensureSessionId = useCallback(async (jobTitleOverride?: string | null): Promise<string> => {
    if (activeSessionId && activeSessionId !== 'new') {
      sessionIdRef.current = activeSessionId
      setSessionId(activeSessionId)
      return activeSessionId
    }

    const current = sessionIdRef.current
    if (current) return current

    if (creatingSessionRef.current) {
      return creatingSessionRef.current
    }

    const pending = createInterviewSession({
      personnel_id: perNeoId,
      org_id: orgNeoId,
      job_title: jobTitleOverride || initialJobTitle || 'Vị trí chưa xác định',
    }).then((created) => {
      const nextId = created.session_id
      sessionIdRef.current = nextId
      setSessionId(nextId)
      localStorage.setItem(localStorageKey, nextId)
      return nextId
    }).finally(() => {
      creatingSessionRef.current = null
    })

    creatingSessionRef.current = pending
    return pending
  }, [activeSessionId, initialJobTitle, localStorageKey, orgNeoId, perNeoId])

  // Load lịch sử khi mount
  useEffect(() => {
    let cancelled = false

    const closeCurrentSocket = () => {
      try {
        wsRef.current?.close()
      } catch {
      }
      wsRef.current = null
    }

    const load = async () => {
      closeCurrentSocket()
      assistantContentRef.current = ''
      setIsStreaming(false)
      setStatus('open')
      setMessages([])
      sessionIdRef.current = null
      setSessionId(null)

      if (!orgNeoId || !perNeoId) {
        setHistoryLoaded(true)
        return
      }

      try {
        setHistoryLoaded(false)

        if (createSessionOnMount || activeSessionId === 'new') {
          const nextSessionId = await ensureSessionId(initialJobTitle)
          if (cancelled) return

          setMessages([])
          localStorage.setItem(localStorageKey, nextSessionId)
          localStorage.setItem(
            transcriptStorageKey,
            JSON.stringify({ sessionId: nextSessionId, messages: [] }),
          )
          return
        }

        if (activeSessionId && activeSessionId !== 'new') {
          const history = await getInterviewHistory(activeSessionId)
          if (cancelled) return

          const items = history?.messages ?? []
          setSessionId(activeSessionId)
          sessionIdRef.current = activeSessionId
          localStorage.setItem(localStorageKey, activeSessionId)
          localStorage.setItem(
            transcriptStorageKey,
            JSON.stringify({
              sessionId: activeSessionId,
              messages: items,
            }),
          )
          setMessages(items)
          return
        }

        const storedTranscriptRaw = localStorage.getItem(transcriptStorageKey)
        if (storedTranscriptRaw) {
          try {
            const storedTranscript = JSON.parse(storedTranscriptRaw) as {
              sessionId?: string
              messages?: ChatMessage[]
            }
            const storedTranscriptSessionId = String(storedTranscript.sessionId ?? '').trim()
            const storedTranscriptMessages = Array.isArray(storedTranscript.messages)
              ? storedTranscript.messages
              : []

            if (storedTranscriptSessionId && storedTranscriptMessages.length > 0) {
              setSessionId(storedTranscriptSessionId)
              sessionIdRef.current = storedTranscriptSessionId
              localStorage.setItem(localStorageKey, storedTranscriptSessionId)
              setMessages(storedTranscriptMessages)
              return
            }
          } catch {
          }
        }

        if (requestedSessionId && requestedSessionId !== 'new') {
          const history = await getInterviewHistory(requestedSessionId)
          if (cancelled) return

          setSessionId(requestedSessionId)
          sessionIdRef.current = requestedSessionId
          localStorage.setItem(localStorageKey, requestedSessionId)
          localStorage.setItem(
            transcriptStorageKey,
            JSON.stringify({
              sessionId: requestedSessionId,
              messages: (history?.messages ?? []).map(h => ({
                id:      h.id ?? crypto.randomUUID(),
                role:    h.role,
                content: h.content,
              })),
            }),
          )
          setMessages(
            (history?.messages ?? []).map(h => ({
              id:      h.id ?? crypto.randomUUID(),
              role:    h.role,
              content: h.role === 'assistant' ? formatAssistantText(h.content) : h.content,
            }))
          )
          return
        }

        const storedSession = localStorage.getItem(localStorageKey)
        if (storedSession) {
          const history = await getInterviewHistory(storedSession)
          if (cancelled) return

          const items = history?.messages ?? []
          setSessionId(storedSession)
          sessionIdRef.current = storedSession
          localStorage.setItem(
            transcriptStorageKey,
            JSON.stringify({
              sessionId: storedSession,
              messages: items.map(h => ({
                id:      h.id ?? crypto.randomUUID(),
                role:    h.role,
                content: h.content,
              })),
            }),
          )
          setMessages(
            (items as ChatHistoryItem[]).map(h => ({
              id:      h.id ?? crypto.randomUUID(),
              role:    h.role,
              content: h.content,
            }))
          )
          return
        }

        // Fallback: load newest session from backend for this org/personnel pair.
        const sessions = await getInterviewSessions(orgNeoId)
        if (cancelled) return

        const matched = (sessions || [])
          .filter(s => s.personnel_id === perNeoId)
          .sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at))[0]

        if (matched?.session_id) {
          const history = await getInterviewHistory(matched.session_id)
          if (cancelled) return

          setSessionId(matched.session_id)
          sessionIdRef.current = matched.session_id
          localStorage.setItem(localStorageKey, matched.session_id)
          localStorage.setItem(
            transcriptStorageKey,
            JSON.stringify({
              sessionId: matched.session_id,
              messages: (history?.messages ?? []).map(h => ({
                id:      h.id ?? crypto.randomUUID(),
                role:    h.role,
                content: h.content,
              })),
            }),
          )
          setMessages(
            (history?.messages ?? []).map(h => ({
              id:      h.id ?? crypto.randomUUID(),
              role:    h.role,
              content: h.role === 'assistant' ? formatAssistantText(h.content) : h.content,
            }))
          )
        }
      } catch {
      } finally {
        if (!cancelled) setHistoryLoaded(true)
      }
    }

    load()
    return () => {
      cancelled = true
      closeCurrentSocket()
    }
  }, [
    createSessionOnMount,
    ensureSessionId,
    initialJobTitle,
    localStorageKey,
    orgNeoId,
    perNeoId,
    requestedSessionId,
    activeSessionId,
  ])

  const send = useCallback(async (question: string) => {
    if (isStreaming) return

    const supabase = createClient()
    const { data: { session } } = await supabase.auth.getSession()
    if (!session?.access_token) return
    const resolvedSessionId = await ensureSessionId()

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

    saveInterviewMessage({
      personnel_id:    perNeoId,
      session_id:      resolvedSessionId,
      role:            'user',
      content:         question,
      job_title:       initialJobTitle || undefined,
      is_private_mode: false,
    }).catch(() => {})

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
        session_id:   resolvedSessionId,
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
        const formattedContent = formatAssistantText(assistantContentRef.current)

        setMessages(prev => {
          const last = prev[prev.length - 1]
          if (last?.streaming && last.id === assistantId) {
            return [
              ...prev.slice(0, -1),
              { ...last, content: formattedContent },
            ]
          }
          return [...prev, {
            id:        assistantId,
            role:      'assistant' as const,
            content:   formattedContent,
            streaming: true,
          }]
        })
      }

      if ('done' in data) {
        const assistantContent  = formatAssistantText(assistantContentRef.current)
        const isPrivate         = data.is_private_mode
        assistantContentRef.current = ''

        setMessages(prev => prev.map(m =>
          m.id === assistantId ? { ...m, streaming: false } : m
        ))
        setIsStreaming(false)
        setStatus('open')

        // Persist assistant response (the missing piece)
        if (assistantContent) {
          saveInterviewMessage({
            personnel_id:    perNeoId,
            session_id:      resolvedSessionId,
            role:            'assistant',
            content:         assistantContent,
            job_title:       initialJobTitle || undefined,
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

  }, [ensureSessionId, initialJobTitle, isStreaming, perNeoId, status])

  return { messages, status, historyLoaded, isStreaming, send, sessionId: currentSessionId }
}

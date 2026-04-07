import { apiClient } from "./client"
import type { ChatHistoryItem } from "@/types"

export interface ReasoningSummary {
  skills: string[]
  seniority_years: number | null
  connection_strength: number | null
  match_score: number | null
}

export interface InterviewSession {
  session_id: string
  personnel_id: string
  personnel_name: string
  job_title: string
  reasoning_summary: ReasoningSummary | null
  created_at: string
  last_message: string | null
  message_count: number
}

export interface ChatHistoryResponse {
  messages: ChatHistoryItem[]
}

export interface SessionFitSummaryResponse {
  session_id: string
  fit_summary: string | null
  reasoning_summary: ReasoningSummary | null
}

export interface SaveChatMessagePayload {
  personnel_id: string
  session_id: string
  role: "user" | "assistant"
  content: string
  job_title?: string
  is_private_mode?: boolean
  reasoning?: Record<string, unknown>
}

export interface CreateInterviewSessionPayload {
  personnel_id: string
  org_id: string
  job_title: string
  reasoning_summary?: ReasoningSummary
}

function toFiniteNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string") {
    const parsed = Number.parseFloat(value.trim())
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function toSkills(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item ?? "").trim()).filter(Boolean)
  }

  if (typeof value === "string") {
    const text = value.trim()
    if (!text) return []

    try {
      const parsed = JSON.parse(text)
      if (Array.isArray(parsed)) {
        return parsed.map((item) => String(item ?? "").trim()).filter(Boolean)
      }
    } catch {
      // fallback for non-JSON strings
    }

    return text
      .replace(/^\[/, "")
      .replace(/\]$/, "")
      .split(",")
      .map((item) => item.trim().replace(/^['\"]|['\"]$/g, ""))
      .filter((item) => item.length > 1)
  }

  return []
}

function normalizeReasoningSummary(raw: unknown): ReasoningSummary | null {
  if (!raw || typeof raw !== "object") return null
  const o = raw as Record<string, unknown>

  const normalized: ReasoningSummary = {
    skills: toSkills(o.skills),
    seniority_years: toFiniteNumber(o.seniority_years),
    connection_strength: toFiniteNumber(o.connection_strength),
    match_score: toFiniteNumber(o.match_score),
  }

  if (
    normalized.skills.length === 0
    && normalized.seniority_years === null
    && normalized.connection_strength === null
    && normalized.match_score === null
  ) {
    return null
  }

  return normalized
}

export async function getInterviewSessions(orgId: string): Promise<InterviewSession[]> {
  const response = await apiClient.get<InterviewSession[]>(
    `/chat/sessions?org_id=${encodeURIComponent(orgId)}`,
  )
  return (response.data ?? []).map((session) => ({
    ...session,
    reasoning_summary: normalizeReasoningSummary(session.reasoning_summary),
  }))
}

export async function createInterviewSession(
  payload: CreateInterviewSessionPayload,
): Promise<{ session_id: string }> {
  const response = await apiClient.post<{ session_id: string }>("/chat/sessions", payload)
  return response.data
}

export async function getInterviewHistory(sessionId: string): Promise<ChatHistoryResponse> {
  const response = await apiClient.get<ChatHistoryResponse>(
    `/chat/history/${encodeURIComponent(sessionId)}`,
  )
  return response.data
}

export async function getSessionFitSummary(
  orgId: string,
  sessionId: string,
): Promise<SessionFitSummaryResponse> {
  const response = await apiClient.get<SessionFitSummaryResponse>(
    `/chat/sessions/${encodeURIComponent(sessionId)}/fit-summary?org_id=${encodeURIComponent(orgId)}`,
  )

  const raw = response.data
  return {
    session_id: String(raw?.session_id ?? sessionId),
    fit_summary: typeof raw?.fit_summary === "string" && raw.fit_summary.trim()
      ? raw.fit_summary.trim()
      : null,
    reasoning_summary: normalizeReasoningSummary(raw?.reasoning_summary),
  }
}

export async function saveInterviewMessage(
  payload: SaveChatMessagePayload,
): Promise<{ status: string }> {
  const response = await apiClient.post<{ status: string }>("/chat/message", payload)
  return response.data
}
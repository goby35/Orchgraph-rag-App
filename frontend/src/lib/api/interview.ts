import type { paths } from "@/types/api"

import { apiClient } from "./client"
import { ChatHistoryItem } from "@/types"

type InterviewBody =
  paths["/interview"]["post"]["requestBody"]["content"]["application/json"]
type InterviewResponse =
  paths["/interview"]["post"]["responses"]["200"]["content"]["application/json"]

export interface ChatHistoryResponse {
  messages: ChatHistoryItem[]
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

export interface CreateChatSessionPayload {
  personnel_id: string
  org_id: string
  job_title?: string
}

export interface ChatSessionItem {
  session_id: string
  personnel_id: string
  job_title?: string | null
  last_message: string
  created_at: string
}

export const sendInterviewMessage = (
  body: InterviewBody,
): Promise<InterviewResponse> =>
  apiClient.post<InterviewResponse>("/interview", body).then((r) => r.data)

export const getChatHistory = (
  sessionId: string,
): Promise<ChatHistoryResponse> =>
  apiClient
    .get<ChatHistoryResponse>(
      `/chat/history/${encodeURIComponent(sessionId)}`,
    )
    .then((r) => r.data)

export const createChatSession = (
  payload: CreateChatSessionPayload,
): Promise<{ session_id: string }> =>
  apiClient.post<{ session_id: string }>("/chat/sessions", payload).then((r) => r.data)

export const getChatSessions = (
  orgId: string,
): Promise<ChatSessionItem[]> =>
  apiClient
    .get<ChatSessionItem[]>(`/chat/sessions?org_id=${encodeURIComponent(orgId)}`)
    .then((r) => r.data)

export const saveChatMessage = (
  payload: SaveChatMessagePayload,
): Promise<
  paths["/chat/message"]["post"]["responses"]["200"]["content"]["application/json"]
> =>
  apiClient.post("/chat/message", payload).then((r) => r.data)


export interface ChatConversation {
  org_neo4j_id: string
  org_name?:    string
  messages:     ChatHistoryItem[]
  last_message_at?: string
}

// Lấy toàn bộ chat history của personnel — grouped by org
// Shape thực tế chưa rõ — sẽ điều chỉnh sau khi có curl response
export const getPersonnelChatHistory = (perNeoId: string): Promise<ChatConversation[]> =>
  apiClient.get(`/chat/history/${perNeoId}`).then(r => r.data)


// Thêm vào cuối src/lib/api/interview.ts

export type ConnectionStatus = "pending" | "accepted" | "cancelled" | null

export const getConnectionStatus = (perNeoId: string): Promise<{ status: ConnectionStatus }> =>
  apiClient.get(`/interview/connection-status/${perNeoId}`).then(r => r.data)

export const sendInterviewRequest = (perNeoId: string): Promise<{ status: string; message: string }> =>
  apiClient.post(`/interview/request/${perNeoId}`).then((r) => r.data)

export const acceptInterviewRequest = (perNeoId: string): Promise<{ status: string }> =>
  apiClient.patch(`/interview/request/${perNeoId}/accept`).then((r) => r.data)

export const rejectInterviewRequest = (perNeoId: string): Promise<{ status: string }> =>
  apiClient.patch(`/interview/request/${perNeoId}/reject`).then((r) => r.data)

export interface PersonnelProfile {
  neo4j_id:   string
  name:       string
  skills:     string[]
  summary:    string
  experience: unknown[]
}

export const getPersonnelProfile = (perNeoId: string): Promise<PersonnelProfile> =>
  apiClient.get<PersonnelProfile>(`/interview/profile/${perNeoId}`).then((r) => r.data)
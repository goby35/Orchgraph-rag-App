import type { paths } from "@/types/api"

import { apiClient } from "./client"
import { ChatHistoryItem } from "@/types"

type InterviewBody =
  paths["/interview"]["post"]["requestBody"]["content"]["application/json"]
type InterviewResponse =
  paths["/interview"]["post"]["responses"]["200"]["content"]["application/json"]
type ChatHistoryResponse =
  paths["/chat/history/{per_neo4j_id}"]["get"]["responses"]["200"]["content"]["application/json"]
type MessageBody =
  paths["/chat/message"]["post"]["requestBody"]["content"]["application/json"]

export const sendInterviewMessage = (
  body: InterviewBody,
): Promise<InterviewResponse> =>
  apiClient.post<InterviewResponse>("/interview", body).then((r) => r.data)

export const getChatHistory = (
  perNeoId: string,
): Promise<ChatHistoryResponse> =>
  apiClient
    .get<ChatHistoryResponse>(
      `/chat/history/${encodeURIComponent(perNeoId)}`,
    )
    .then((r) => r.data)

export const saveChatMessage = (
  payload: MessageBody,
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
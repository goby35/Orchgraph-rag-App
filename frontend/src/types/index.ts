import type { components } from "./api"
import type { ReasoningSummary } from "@/lib/api/chat"

export type { components, paths } from "./api"

/** Bản ghi thông báo — khớp `components["schemas"]["NotificationResponse"]` */
export type NotificationPayload = components["schemas"]["NotificationResponse"]

/** Slot rảnh — khớp schema OpenAPI */
export type AvailableSlot = components["schemas"]["AvailableSlot"]

/** User types (từ Supabase auth metadata + bridge) */
export interface AuthUser {
  id: string
  email: string
  role: "organization" | "personnel"
  neo4j_id: string
  full_name: string
}

/** Chat types (WebSocket + UI) */
export interface ChatMessage {
  id: string
  role: "user" | "assistant"
  content: string
  streaming?: boolean
}

// export interface WsChunk {
//   type: "chunk" | "done" | "error"
//   content?: string
//   message_id?: string
//   error?: string
// }

export type WsChunk =
  | { chunk: string }
  | { done: true; is_private_mode: boolean }
  | { error: string }

/** Kết quả tìm kiếm ứng viên (POST /search → `results[]`) */
export interface CandidateResult {
  id: string
  name: string
  summary: string
  score: number
  skills: string[]
  personnel_id?: string
  reasoning_summary?: ReasoningSummary | null
  context?: string[]
}

/** Dữ liệu node React Flow — Personnel */
export interface PersonnelNodeData {
  id: string
  label: string
  summary?: string
  skills?: string[]
  availability: boolean
  score?: number
}

/** Dữ liệu node React Flow — Organization */
export interface OrgNodeData {
  id: string
  label: string
  industry?: string
}

export type WsStatus = 'connecting' | 'open' | 'closed' | 'error'

export interface ChatHistoryItem {
  id:              string
  role:            'user' | 'assistant'
  content:         string
  is_private_mode: boolean
  created_at:      string
}

export type ScheduleStatus =
  | 'pending'
  | 'confirmed'
  | 'rescheduled'
  | 'awaiting_org_response'
  | 'awaiting_personnel_response'
  | 'cancelled'
  | 'completed'

export type MeetingFormat = 'online' | 'offline'

export interface ScheduleRecord {
  id:               string
  org_neo4j_id:     string
  per_neo4j_id:     string
  proposed_at:      string   // ISO datetime
  rescheduled_at:   string | null
  confirmed_at:     string | null
  duration_minutes: number
  format:           MeetingFormat
  location:         string | null
  status:           ScheduleStatus
  chat_summary:     string | null
  reschedule_history?: ScheduleHistoryEntry[] | null
  email_sent:       boolean
  created_at:       string
}

export interface ScheduleHistoryEntry {
  by: 'org' | 'personnel'
  proposed_time: string
  timestamp: string
  notes?: string | null
}
import { apiClient } from "./client"

export type ConnectStatus = "accepted" | "pending"

export interface ConnectResponse {
  status: ConnectStatus
  auto_connected: boolean
  message: string
}

export interface RespondConnectionResponse {
  status: "accepted" | "declined"
  message: string
}

export async function connectToPersonnel(params: {
  personnel_id: string
  org_id: string
  match_score: number
  job_title: string
}): Promise<ConnectResponse> {
  const res = await apiClient.post<ConnectResponse>("/connect", params)
  return res.data
}

export async function respondConnection(params: {
  org_id: string
  personnel_id: string
  action: "accept" | "decline"
}): Promise<RespondConnectionResponse> {
  const res = await apiClient.patch<RespondConnectionResponse>(
    `/connect/${encodeURIComponent(params.personnel_id)}/respond`,
    {
      org_id: params.org_id,
      action: params.action,
    },
  )
  return res.data
}

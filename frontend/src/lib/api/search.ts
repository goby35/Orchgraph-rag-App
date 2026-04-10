import type { paths } from "@/types/api"
import type { CandidateResult, ConnectionStatus } from "@/types"

import type { ReasoningSummary } from "./chat"

import { apiClient } from "./client"

type SearchBody =
  paths["/search"]["post"]["requestBody"]["content"]["application/json"]
type SearchResponse =
  paths["/search"]["post"]["responses"]["200"]["content"]["application/json"]

export const searchCandidates = async (
  body: SearchBody,
): Promise<SearchResponse> => {
  const res = await apiClient.post<SearchResponse>("/search", body)
  return res.data
}

/** Parse JSON trả về từ POST /search (`{ results: [...] }`). */
export function mapSearchResponseToCandidates(data: unknown): CandidateResult[] {
  if (!data || typeof data !== "object") return []
  const r = data as Record<string, unknown>
  const results = r.results
  if (!Array.isArray(results)) return []

  const isConnectionStatus = (value: unknown): value is ConnectionStatus =>
    value === "not_connected" ||
    value === "pending_sent" ||
    value === "accepted" ||
    value === "declined"

  return results.map((item): CandidateResult => {
    const o = item as Record<string, unknown>
    const scoreRaw = o.score
    const score =
      typeof scoreRaw === "number"
        ? scoreRaw
        : typeof scoreRaw === "string"
          ? Number.parseFloat(scoreRaw)
          : Number(scoreRaw)
    const skills = Array.isArray(o.skills) ? o.skills.map(String) : []
    const matchScoreRaw = o.match_score
    const matchScore =
      typeof matchScoreRaw === "number"
        ? matchScoreRaw
        : typeof matchScoreRaw === "string"
          ? Number.parseFloat(matchScoreRaw)
          : score
    const connectionStatusRaw = o.connection_status
    const connectionStatus: ConnectionStatus = isConnectionStatus(connectionStatusRaw)
      ? connectionStatusRaw
      : "not_connected"
    const reasoningSummary: ReasoningSummary = {
      skills,
      seniority_years: null,
      connection_strength: null,
      match_score: Number.isFinite(matchScore) ? matchScore : 0,
    }
    return {
      id: String(o.id ?? ""),
      name: String(o.name ?? ""),
      summary: String(o.summary ?? ""),
      score: Number.isFinite(score) ? score : 0,
      match_score: Number.isFinite(matchScore) ? matchScore : 0,
      skills,
      personnel_id: String(o.personnel_id ?? o.id ?? ""),
      connection_status: connectionStatus,
      reasoning_summary: reasoningSummary,
      context: undefined,
    }
  })
}

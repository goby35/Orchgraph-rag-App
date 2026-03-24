import type { paths } from "@/types/api"
import type { CandidateResult } from "@/types"

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
  return results.map((item): CandidateResult => {
    const o = item as Record<string, unknown>
    const scoreRaw = o.score
    const score =
      typeof scoreRaw === "number"
        ? scoreRaw
        : typeof scoreRaw === "string"
          ? Number.parseFloat(scoreRaw)
          : Number(scoreRaw)
    return {
      id: String(o.id ?? ""),
      name: String(o.name ?? ""),
      summary: String(o.summary ?? ""),
      score: Number.isFinite(score) ? score : 0,
      skills: Array.isArray(o.skills) ? o.skills.map(String) : [],
      context: undefined,
    }
  })
}

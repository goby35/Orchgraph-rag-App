import type { paths } from "@/types/api"

import { apiClient } from "./client"

type GraphResponse =
  paths["/graph"]["get"]["responses"]["200"]["content"]["application/json"]

export const getGraph = async (
  showAll?: boolean,
  focusId?: string | null,
): Promise<GraphResponse> => {
  const params: Record<string, string | boolean> = {}

  if (showAll !== undefined) {
    params.show_all = showAll
  }

  if (!showAll && focusId) {
    params.focus_id = focusId
  }

  const res = await apiClient.get<GraphResponse>("/graph", {
    params: Object.keys(params).length > 0 ? params : undefined,
  })
  return res.data
}

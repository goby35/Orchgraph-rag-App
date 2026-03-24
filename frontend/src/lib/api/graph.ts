import type { paths } from "@/types/api"

import { apiClient } from "./client"

type GraphResponse =
  paths["/graph"]["get"]["responses"]["200"]["content"]["application/json"]

export const getGraph = async (
  showAll?: boolean,
): Promise<GraphResponse> => {
  const res = await apiClient.get<GraphResponse>("/graph", {
    params:
      showAll === undefined
        ? undefined
        : {
            show_all: showAll,
          },
  })
  return res.data
}

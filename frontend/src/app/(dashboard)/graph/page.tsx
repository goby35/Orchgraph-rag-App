"use client"

import { useQuery } from "@tanstack/react-query"
import { useState } from "react"

import { ErrorState } from "@/components/shared/ErrorState"
import { PageSkeleton } from "@/components/shared/PageSkeleton"
import GraphCanvas, {
  type GraphNodeSelection,
} from "@/components/graph/GraphCanvas"
import { NodeDetailPanel } from "@/components/graph/NodeDetailPanel"
import { getGraph } from "@/lib/api"

export default function OrgGraphPage() {
  const [selected, setSelected] = useState<GraphNodeSelection | null>(null)

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["graph"],
    queryFn: () => getGraph(true),
  })

  if (isLoading) {
    return (
      <div className="flex flex-col gap-6">
        <h1 className="text-2xl font-semibold tracking-tight">
          Đồ thị quan hệ
        </h1>
        <PageSkeleton variant="graph" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col gap-6">
        <h1 className="text-2xl font-semibold tracking-tight">
          Đồ thị quan hệ
        </h1>
        <ErrorState
          message={error instanceof Error ? error.message : "Không tải được đồ thị"}
          onRetry={() => void refetch()}
        />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Đồ thị quan hệ
        </h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Organization ↔ Personnel (CONNECTED_TO). Click node để xem chi tiết.
        </p>
      </div>
      <div className="flex flex-col gap-4 lg:flex-row">
        <div className="min-w-0 flex-1">
          {isFetching && !isLoading ? (
            <div className="text-muted-foreground mb-2 text-xs">
              Đang làm mới…
            </div>
          ) : null}
          <GraphCanvas
            data={data}
            onNodeClick={(sel) => {
              setSelected(sel)
            }}
          />
        </div>
        {selected ? (
          <NodeDetailPanel
            selection={selected}
            onClose={() => {
              setSelected(null)
            }}
          />
        ) : (
          <div className="text-muted-foreground hidden w-72 shrink-0 rounded-lg border border-dashed p-4 text-sm lg:block">
            Chọn một node trên đồ thị để xem chi tiết.
          </div>
        )}
      </div>
    </div>
  )
}

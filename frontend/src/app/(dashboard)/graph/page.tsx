"use client"

import { useQuery } from "@tanstack/react-query"
import { useMemo, useState } from "react"

import { ErrorState } from "@/components/shared/ErrorState"
import { PageSkeleton } from "@/components/shared/PageSkeleton"
import GraphCanvas, {
  transformGraphData,
  type GraphNodeSelection,
} from "@/components/graph/GraphCanvas"
import { NodeDetailPanel } from "@/components/graph/NodeDetailPanel"
import { getGraph } from "@/lib/api"
import { useAuthStore } from "@/store/auth.store"

export default function OrgGraphPage() {
  const [selected, setSelected] = useState<GraphNodeSelection | null>(null)
  const neoId = useAuthStore((state) => state.neoId)

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["graph", neoId],
    queryFn: () => getGraph(false, neoId),
  })

  const graphData = useMemo(() => transformGraphData(data), [data])

  if (isLoading) {
    return (
      <div className="flex flex-col gap-6">
        <h1 className="text-2xl font-bold tracking-tight lg:text-[1.7rem]">
          Đồ thị quan hệ
        </h1>
        <PageSkeleton variant="graph" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col gap-6">
        <h1 className="text-2xl font-bold tracking-tight lg:text-[1.7rem]">
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
        <h1 className="text-2xl font-bold tracking-tight lg:text-[1.7rem]">
          Đồ thị quan hệ
        </h1>
        <p className="text-muted-foreground mt-1.5 text-sm leading-6">
          Hiển thị bạn, các personnel đã kết nối và các node liên quan trực tiếp của họ.
        </p>
      </div>
      <div className="flex flex-col gap-4 lg:flex-row">
        <div className="min-w-0 flex-1">
          {isFetching && !isLoading ? (
            <div className="text-muted-foreground mb-2 text-xs font-medium">
              Đang làm mới…
            </div>
          ) : null}
          <GraphCanvas
            graphData={graphData}
            onNodeClick={(sel) => {
              setSelected(sel)
            }}
            onBackgroundClick={() => {
              setSelected(null)
            }}
            selectedNodeId={selected?.id ?? null}
          />
        </div>
        {selected ? (
          <NodeDetailPanel
            selection={selected}
            graphData={graphData}
            onClose={() => {
              setSelected(null)
            }}
          />
        ) : (
          <div className="text-muted-foreground hidden w-72 shrink-0 rounded-2xl border border-dashed border-border/80 bg-card/70 p-5 text-sm leading-6 lg:block">
            Chọn một node trên đồ thị để xem chi tiết.
          </div>
        )}
      </div>
    </div>
  )
}

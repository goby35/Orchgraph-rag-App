import { Skeleton } from "@/components/ui/skeleton"

export default function ScheduleLoading() {
  return (
    <div className="max-w-4xl mx-auto py-8 px-4 space-y-6">
      <Skeleton className="h-7 w-36" />
      {/* Table header */}
      <div className="border rounded-lg overflow-hidden">
        <div className="grid grid-cols-4 gap-4 p-4 bg-muted/30 border-b">
          {["Ứng viên", "Thời gian", "Trạng thái", "Thao tác"].map(col => (
            <Skeleton key={col} className="h-4 w-20" />
          ))}
        </div>
        {/* Table rows */}
        {[1, 2, 3, 4, 5].map(i => (
          <div key={i} className="grid grid-cols-4 gap-4 p-4 border-b last:border-0">
            <div className="flex items-center gap-2">
              <Skeleton className="h-8 w-8 rounded-full" />
              <Skeleton className="h-4 w-24" />
            </div>
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-6 w-24 rounded-full" />
            <Skeleton className="h-8 w-20 rounded-md" />
          </div>
        ))}
      </div>
    </div>
  )
}
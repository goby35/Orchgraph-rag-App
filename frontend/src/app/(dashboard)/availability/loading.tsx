import { Skeleton } from "@/components/ui/skeleton"

export default function AvailabilityLoading() {
  return (
    <div className="max-w-2xl mx-auto py-8 px-4 space-y-6">
      <Skeleton className="h-7 w-36" />
      <div className="border rounded-lg p-6 space-y-5">
        <Skeleton className="h-5 w-48" />
        {/* 7 day rows */}
        {["T2", "T3", "T4", "T5", "T6", "T7", "CN"].map(day => (
          <div key={day} className="flex items-center gap-4">
            <Skeleton className="h-4 w-8 shrink-0" />
            <Skeleton className="h-9 w-28 rounded-md" />
            <Skeleton className="h-4 w-4" />
            <Skeleton className="h-9 w-28 rounded-md" />
          </div>
        ))}
        <Skeleton className="h-10 w-32 rounded-md" />
      </div>
    </div>
  )
}
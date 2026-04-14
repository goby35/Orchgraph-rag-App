import { Skeleton } from "@/components/ui/skeleton"

export default function AvailabilityLoading() {
  return (
    <div className="mx-auto max-w-2xl space-y-6 px-4 py-8">
      <Skeleton className="h-7 w-36" />
      <div className="space-y-5 rounded-2xl border border-border/70 p-6">
        <Skeleton className="h-5 w-48" />
        {/* 7 day rows */}
        {["T2", "T3", "T4", "T5", "T6", "T7", "CN"].map(day => (
          <div key={day} className="flex items-center gap-4">
            <Skeleton className="h-4 w-8 shrink-0" />
            <Skeleton className="h-9 w-28 rounded-xl" />
            <Skeleton className="h-4 w-4" />
            <Skeleton className="h-9 w-28 rounded-xl" />
          </div>
        ))}
        <Skeleton className="h-10 w-32 rounded-xl" />
      </div>
    </div>
  )
}
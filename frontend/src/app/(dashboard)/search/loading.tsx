import { Skeleton } from "@/components/ui/skeleton"

export default function SearchLoading() {
  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-8 lg:space-y-7">
      <Skeleton className="h-7 w-40" />
      <Skeleton className="h-24 w-full rounded-2xl" />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {[1, 2, 3, 4, 5, 6].map(i => (
          <div key={i} className="space-y-3 rounded-2xl border border-border/70 p-5">
            <div className="flex items-center gap-3">
              <Skeleton className="h-10 w-10 rounded-full" />
              <div className="space-y-1.5 flex-1">
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-3 w-1/2" />
              </div>
            </div>
            <Skeleton className="h-2 w-full rounded-full" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-5/6" />
            <div className="flex gap-1.5 flex-wrap">
              {[1, 2, 3].map(j => (
                <Skeleton key={j} className="h-5 w-16 rounded-full" />
              ))}
            </div>
            <Skeleton className="h-9 w-full rounded-xl" />
          </div>
        ))}
      </div>
    </div>
  )
}
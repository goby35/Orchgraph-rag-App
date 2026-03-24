import { Skeleton } from "@/components/ui/skeleton"

export default function GraphLoading() {
  return (
    <div className="max-w-6xl mx-auto py-8 px-4 space-y-4">
      <Skeleton className="h-7 w-48" />
      <div className="border rounded-lg overflow-hidden h-[600px] relative bg-muted/20">
        {/* Simulate nodes */}
        {[
          { top: "20%", left: "15%" },
          { top: "50%", left: "10%" },
          { top: "75%", left: "20%" },
          { top: "15%", left: "45%" },
          { top: "40%", left: "42%" },
          { top: "65%", left: "48%" },
          { top: "85%", left: "40%" },
          { top: "20%", left: "72%" },
          { top: "50%", left: "75%" },
          { top: "75%", left: "70%" },
        ].map((pos, i) => (
          <Skeleton
            key={i}
            className="absolute h-14 w-14 rounded-full"
            style={{ top: pos.top, left: pos.left }}
          />
        ))}
        {/* Org nodes — rectangular */}
        {[
          { top: "35%", left: "30%" },
          { top: "60%", left: "32%" },
        ].map((pos, i) => (
          <Skeleton
            key={`org-${i}`}
            className="absolute h-10 w-28 rounded-lg"
            style={{ top: pos.top, left: pos.left }}
          />
        ))}
        {/* Loading text center */}
        <div className="absolute inset-0 flex items-center justify-center">
          <p className="text-sm text-muted-foreground animate-pulse">
            Đang tải đồ thị...
          </p>
        </div>
      </div>
    </div>
  )
}
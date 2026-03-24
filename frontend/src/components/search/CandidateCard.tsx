import Link from "next/link"

import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { buttonVariants } from "@/lib/variants"
import { cn } from "@/lib/utils"
import type { CandidateResult } from "@/types"

function initialsFromName(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length >= 2) {
    const a = parts[0]?.[0]
    const b = parts[parts.length - 1]?.[0]
    return `${a ?? ""}${b ?? ""}`.toUpperCase() || "?"
  }
  if (parts.length === 1 && parts[0].length >= 2) {
    return parts[0].slice(0, 2).toUpperCase()
  }
  return parts[0]?.[0]?.toUpperCase() ?? "?"
}

function scoreTone(score: number): "green" | "amber" | "gray" {
  if (score > 0.7) return "green"
  if (score >= 0.4) return "amber"
  return "gray"
}

interface CandidateCardProps {
  candidate: CandidateResult
}

export function CandidateCard({ candidate }: CandidateCardProps) {
  const pct = Math.round(Math.min(1, Math.max(0, candidate.score)) * 100)
  const tone = scoreTone(candidate.score)
  const barClass =
    tone === "green"
      ? "bg-green-500"
      : tone === "amber"
        ? "bg-amber-500"
        : "bg-muted-foreground/50"

// --- FIX TIER 1: Dọn sạch rác LLM và lỗi Array ---
  let rawSkills = candidate.skills || []
  
  if (typeof rawSkills === "string") {
    rawSkills = [rawSkills as string]
  } else if (
    Array.isArray(rawSkills) && 
    rawSkills.length > 0 && 
    rawSkills.every(s => typeof s === 'string' && s.length === 1)
  ) {
    rawSkills = [rawSkills.join("")]
  }

  // BƯỚC MỚI: Xóa dấu nháy kép thừa và khoảng trắng, sau đó mới filter
  const validSkills = rawSkills
    .map(s => typeof s === 'string' ? s.replace(/["']/g, '').trim() : '')
    .filter(s => s.length > 0) // Loại bỏ các chuỗi rỗng sau khi đã xóa ngoặc kép

  const maxSkills = 5
  const skills = validSkills.slice(0, maxSkills)
  const more = validSkills.length - skills.length
  // ------------------------------------------

  return (
    <article className="bg-card flex flex-col rounded-xl border p-4 shadow-sm">
      <div className="flex gap-3">
        <Avatar className="size-11 shrink-0">
          <AvatarFallback className="text-xs">
            {initialsFromName(candidate.name)}
          </AvatarFallback>
        </Avatar>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate font-semibold">{candidate.name}</h3>
            <span
              className={cn(
                "rounded-full px-2 py-0.5 text-xs font-medium",
                tone === "green" && "bg-green-500/15 text-green-700 dark:text-green-400",
                tone === "amber" &&
                  "bg-amber-500/15 text-amber-800 dark:text-amber-300",
                tone === "gray" && "bg-muted text-muted-foreground",
              )}
            >
              {tone === "green"
                ? "Phù hợp cao"
                : tone === "amber"
                  ? "Trung bình"
                  : "Thấp"}
            </span>
          </div>
          <div className="mt-2 space-y-1">
            <div className="flex items-center justify-between gap-2 text-xs">
              <span className="text-muted-foreground">Match</span>
              <span className="font-medium tabular-nums">{pct}%</span>
            </div>
            <div className="bg-muted h-2 w-full overflow-hidden rounded-full">
              <div
                className={cn("h-full rounded-full transition-all", barClass)}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        </div>
      </div>
      <p className="text-muted-foreground mt-3 line-clamp-2 text-sm">
        {candidate.summary || "—"}
      </p>
      {skills.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {/* TRUYỀN THÊM index VÀO HÀM MAP VÀ ĐỔI KEY */}
            {skills.map((s, index) => (
              <span
                key={`${s}-${index}`} 
                className="bg-muted text-muted-foreground rounded-md px-2 py-0.5 text-xs"
              >
                {s}
              </span>
            ))}
            {more > 0 ? (
              <span className="text-muted-foreground text-xs">+{more} khác</span>
            ) : null}
          </div>
        ) : null}
      <div className="mt-4 flex justify-end border-t pt-3">
        <Link
          href={`/interview/${encodeURIComponent(candidate.id)}`}
          className={buttonVariants({ variant: "default", size: "sm" })}
        >
          Phỏng vấn
        </Link>
      </div>
    </article>
  )
}

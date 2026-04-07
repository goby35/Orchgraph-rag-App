"use client"

import { useEffect } from "react"
import { useRouter, useSearchParams } from "next/navigation"

export default function InterviewEntryClient() {
  const router = useRouter()
  const searchParams = useSearchParams()

  const personnelId = searchParams.get("personnelId")?.trim() ?? ""
  const jobTitle = searchParams.get("jobTitle")?.trim() ?? ""
  const sessionId = searchParams.get("sessionId")?.trim() || "new"

  useEffect(() => {
    if (!personnelId) return

    const nextParams = new URLSearchParams({
      jobTitle,
      sessionId,
    })

    router.replace(`/interview/${encodeURIComponent(personnelId)}?${nextParams.toString()}`)
  }, [jobTitle, personnelId, router, sessionId])

  if (!personnelId) {
    return (
      <div className="rounded-lg border bg-card p-6 text-sm text-muted-foreground">
        Thiếu personnelId để mở phiên phỏng vấn.
      </div>
    )
  }

  return (
    <div className="rounded-lg border bg-card p-6 text-sm text-muted-foreground">
      Đang mở phiên phỏng vấn...
    </div>
  )
}
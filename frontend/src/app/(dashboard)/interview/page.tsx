import { Suspense } from "react"

import InterviewEntryClient from "../../../components/interview/InterviewEntryClient"

export default function InterviewEntryPage() {
  return (
    <Suspense
      fallback={
        <div className="rounded-2xl border border-border/70 bg-card/90 p-6 text-sm font-medium text-muted-foreground shadow-sm">
          Đang mở phiên phỏng vấn...
        </div>
      }
    >
      <InterviewEntryClient />
    </Suspense>
  )
}

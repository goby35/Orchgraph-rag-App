import { Suspense } from "react"

import InterviewEntryClient from "../../../components/interview/InterviewEntryClient"

export default function InterviewEntryPage() {
  return (
    <Suspense
      fallback={
        <div className="rounded-lg border bg-card p-6 text-sm text-muted-foreground">
          Đang mở phiên phỏng vấn...
        </div>
      }
    >
      <InterviewEntryClient />
    </Suspense>
  )
}

"use client"

import { ErrorState } from "@/components/shared/ErrorState"
import { PageSkeleton } from "@/components/shared/PageSkeleton"
import type { CandidateResult } from "@/types"

import { CandidateCard } from "./CandidateCard"

interface SearchResultsProps {
  results: CandidateResult[]
  jobTitle: string
  loading: boolean
  error: unknown
  searched: boolean
  onRetry?: () => void
  onStartInterview?: (candidate: CandidateResult) => void | Promise<void>
}

function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message
  if (typeof err === "string") return err
  try {
    return JSON.stringify(err)
  } catch {
    return "Lỗi không xác định"
  }
}

export function SearchResults({
  results,
  jobTitle,
  loading,
  error,
  searched,
  onRetry,
  onStartInterview,
}: SearchResultsProps) {
  if (loading) {
    return <PageSkeleton variant="card-list" />
  }

  if (error != null) {
    return (
      <ErrorState
        message={errorMessage(error)}
        onRetry={onRetry}
      />
    )
  }

  if (!searched) {
    return (
      <p className="text-muted-foreground text-center text-sm">
        Nhập mô tả công việc để tìm ứng viên phù hợp.
      </p>
    )
  }

  if (results.length === 0) {
    return (
      <p className="text-muted-foreground text-center text-sm">
        Không tìm thấy ứng viên phù hợp.
      </p>
    )
  }

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
      {results.map((c) => (
        <CandidateCard
          key={c.id}
          candidate={c}
          jobTitle={jobTitle}
          onStartInterview={onStartInterview}
        />
      ))}
    </div>
  )
}

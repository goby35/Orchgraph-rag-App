"use client"

import { useMutation } from "@tanstack/react-query"
import { useState } from "react"

import { SearchBar } from "@/components/search/SearchBar"
import { SearchResults } from "@/components/search/SearchResults"
import { mapSearchResponseToCandidates, searchCandidates } from "@/lib/api"
import type { CandidateResult } from "@/types"

export default function OrgSearchPage() {
  const [results, setResults] = useState<CandidateResult[]>([])
  const [searched, setSearched] = useState(false)
  const [lastQuery, setLastQuery] = useState("")

  const mutation = useMutation({
    mutationFn: (query: string) =>
      searchCandidates({ query, top_k: 10 }),
    onSuccess: (data) => {
      setResults(mapSearchResponseToCandidates(data))
      setSearched(true)
    },
  })

  function handleSearch(query: string) {
    setLastQuery(query)
    mutation.mutate(query)
  }

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Tìm kiếm ứng viên
        </h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Dán hoặc nhập mô tả công việc (JD), sau đó nhấn Tìm ứng viên.
        </p>
      </div>
      <SearchBar onSearch={handleSearch} loading={mutation.isPending} />
      <SearchResults
        results={results}
        loading={mutation.isPending}
        error={mutation.error}
        searched={searched}
        onRetry={
          lastQuery
            ? () => {
                mutation.mutate(lastQuery)
              }
            : undefined
        }
      />
    </div>
  )
}

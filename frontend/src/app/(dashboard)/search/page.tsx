"use client"

import { useMutation } from "@tanstack/react-query"
import Link from "next/link"
import { useEffect, useState } from "react"

import { SearchBar } from "@/components/search/SearchBar"
import { SearchResults } from "@/components/search/SearchResults"
import { mapSearchResponseToCandidates, searchCandidates } from "@/lib/api"
import { cn } from "@/lib/utils"
import type { CandidateResult } from "@/types"

// ── Search history (localStorage) ────────────────────────────────────────────

interface SearchHistoryEntry {
  id:        string
  query:     string
  timestamp: number
  results:   CandidateResult[]
}

const HISTORY_KEY = "org_search_history"
const MAX_HISTORY = 5

function loadHistory(): SearchHistoryEntry[] {
  try {
    const raw = typeof window !== "undefined" ? localStorage.getItem(HISTORY_KEY) : null
    return raw ? (JSON.parse(raw) as SearchHistoryEntry[]) : []
  } catch {
    return []
  }
}

function saveHistory(entry: SearchHistoryEntry): void {
  try {
    const prev = loadHistory().filter(e => e.query !== entry.query)
    localStorage.setItem(HISTORY_KEY, JSON.stringify([entry, ...prev].slice(0, MAX_HISTORY)))
  } catch { /* noop */ }
}

// ── RecentSearchHistory component ─────────────────────────────────────────────

function RecentSearchHistory({ history }: { history: SearchHistoryEntry[] }) {
  const [open, setOpen]         = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)

  if (history.length === 0) return null

  return (
    <div className="border rounded-lg overflow-hidden text-sm">
      {/* Header toggle */}
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-4 py-3 font-medium hover:bg-muted/50 transition-colors"
      >
        <span>Tìm kiếm gần đây</span>
        <span className="text-xs text-muted-foreground">
          {history.length} lần {open ? "▲" : "▼"}
        </span>
      </button>

      {open && (
        <div className="divide-y border-t">
          {history.map(entry => (
            <div key={entry.id} className="px-4 py-3 space-y-2">

              {/* Search header — click to expand candidates */}
              <button
                onClick={() => setExpanded(expanded === entry.id ? null : entry.id)}
                className="w-full text-left"
              >
                <div className="flex items-start justify-between gap-3">
                  <p className="text-xs text-muted-foreground line-clamp-2 flex-1">
                    {entry.query.length > 120
                      ? entry.query.slice(0, 120) + "…"
                      : entry.query}
                  </p>
                  <div className="shrink-0 text-right space-y-0.5">
                    <p className="text-[11px] text-muted-foreground whitespace-nowrap">
                      {new Date(entry.timestamp).toLocaleString("vi-VN", {
                        day: "2-digit", month: "2-digit",
                        hour: "2-digit", minute: "2-digit",
                      })}
                    </p>
                    <p className="text-[11px] text-muted-foreground">
                      {entry.results.length} ứng viên {expanded === entry.id ? "▲" : "▼"}
                    </p>
                  </div>
                </div>
              </button>

              {/* Candidate list */}
              {expanded === entry.id && (
                <div className="space-y-1 pt-1">
                  {entry.results.map(c => {
                    const pct  = Math.round(Math.min(1, Math.max(0, c.score)) * 100)
                    const tone = pct >= 70 ? "green" : pct >= 40 ? "amber" : "gray"
                    return (
                      <Link
                        key={c.id}
                        href={`/interview/${encodeURIComponent(c.id)}`}
                        className="flex items-center justify-between gap-3 px-3 py-2 rounded-md hover:bg-muted/60 transition-colors"
                      >
                        <span className="truncate text-sm">{c.name || c.id}</span>
                        <div className="flex items-center gap-2 shrink-0">
                          <span className={cn(
                            "text-xs font-medium tabular-nums",
                            tone === "green" && "text-green-700",
                            tone === "amber" && "text-amber-700",
                            tone === "gray"  && "text-muted-foreground",
                          )}>
                            {pct}%
                          </span>
                          {/* Relationship status: not available without extra API call */}
                          <span className="text-[11px] text-muted-foreground border rounded px-1.5 py-0.5">
                            —
                          </span>
                        </div>
                      </Link>
                    )
                  })}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function OrgSearchPage() {
  const [results,   setResults]   = useState<CandidateResult[]>([])
  const [searched,  setSearched]  = useState(false)
  const [lastQuery, setLastQuery] = useState("")
  const [history,   setHistory]   = useState<SearchHistoryEntry[]>([])

  useEffect(() => {
    setHistory(loadHistory())
  }, [])

  const mutation = useMutation({
    mutationFn: (query: string) =>
      searchCandidates({ query, top_k: 10 }),
    onSuccess: (data, query) => {
      const candidates = mapSearchResponseToCandidates(data)
      setResults(candidates)
      setSearched(true)

      if (candidates.length > 0) {
        const entry: SearchHistoryEntry = {
          id:        crypto.randomUUID(),
          query,
          timestamp: Date.now(),
          results:   candidates,
        }
        saveHistory(entry)
        setHistory(loadHistory())
      }
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

      <RecentSearchHistory history={history} />

      <SearchResults
        results={results}
        loading={mutation.isPending}
        error={mutation.error}
        searched={searched}
        onRetry={
          lastQuery
            ? () => { mutation.mutate(lastQuery) }
            : undefined
        }
      />
    </div>
  )
}

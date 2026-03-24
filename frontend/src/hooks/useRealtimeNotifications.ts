"use client"

import { useQueryClient } from "@tanstack/react-query"
import { useEffect } from "react"

import { createClient } from "@/lib/supabase/client"

export function useRealtimeNotifications(neoId: string | null) {
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!neoId) return

    const supabase = createClient()
    const channel = supabase
      .channel(`notifications:${neoId}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "vdme",
          table: "notifications",
          filter: `recipient_neo4j_id=eq.${neoId}`,
        },
        () => {
          queryClient.invalidateQueries({ queryKey: ["notifications"] })
          queryClient.invalidateQueries({ queryKey: ["unread-count"] })
        },
      )
      .subscribe()

    return () => {
      void supabase.removeChannel(channel)
    }
  }, [neoId, queryClient])
}

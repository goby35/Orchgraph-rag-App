"use client"

import type { User } from "@supabase/supabase-js"
import { create } from "zustand"

export type AppRole = "organization" | "personnel"

interface AuthState {
  user: User | null
  neoId: string | null
  role: AppRole | null
  setUser: (user: User | null) => void
  setNeoId: (id: string) => void
  clear: () => void
}

function roleFromMetadata(user: User | null): AppRole | null {
  const raw = user?.user_metadata?.role
  if (typeof raw !== "string") return null
  const u = raw.toUpperCase()
  if (u === "ORGANIZATION") return "organization"
  if (u === "PERSONNEL") return "personnel"
  return null
}

function neoIdFromUser(user: User | null): string | null {
  const raw = user?.user_metadata?.neo4j_id
  return typeof raw === "string" && raw.length > 0 ? raw : null
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  neoId: null,
  role: null,
  setUser: (user) =>
    set({
      user,
      role: roleFromMetadata(user),
      neoId: neoIdFromUser(user),
    }),
  setNeoId: (id) => set({ neoId: id }),
  clear: () => set({ user: null, neoId: null, role: null }),
}))

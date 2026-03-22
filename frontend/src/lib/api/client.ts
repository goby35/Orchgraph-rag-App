"use client"

import axios from "axios"

import { createClient } from "@/lib/supabase/client"

export const apiClient = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL,
  headers: { "Content-Type": "application/json" },
})

apiClient.interceptors.request.use(async (config) => {
  const supabase = createClient()
  const {
    data: { session },
  } = await supabase.auth.getSession()
  if (session?.access_token) {
    config.headers.Authorization = `Bearer ${session.access_token}`
  }
  return config
})

apiClient.interceptors.response.use(
  (res) => res,
  (err: unknown) => {
    if (
      typeof window !== "undefined" &&
      axios.isAxiosError(err) &&
      err.response?.status === 401
    ) {
      window.location.href = "/login"
    }
    return Promise.reject(err)
  },
)

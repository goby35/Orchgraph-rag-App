"use client"

import axios, { type InternalAxiosRequestConfig } from "axios"

import { createClient } from "@/lib/supabase/client"

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
const supabase = createClient()

type RetriableConfig = InternalAxiosRequestConfig & { _retry?: boolean }

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: { "Content-Type": "application/json" },
})

apiClient.interceptors.request.use(async (config) => {
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
  async (err: unknown) => {
    if (
      typeof window !== "undefined" &&
      axios.isAxiosError(err) &&
      err.response?.status === 401
    ) {
      const originalRequest = err.config as RetriableConfig | undefined

      if (originalRequest && !originalRequest._retry) {
        originalRequest._retry = true
        const {
          data: { session },
        } = await supabase.auth.refreshSession()

        if (session?.access_token) {
          originalRequest.headers = originalRequest.headers ?? {}
          originalRequest.headers.Authorization = `Bearer ${session.access_token}`
          return apiClient(originalRequest)
        }
      }

      await supabase.auth.signOut()
      window.location.href = "/login"
    }

    return Promise.reject(err)
  },
)

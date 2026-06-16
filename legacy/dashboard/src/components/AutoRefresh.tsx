'use client'
import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

export function useAutoRefresh(intervalMs = 5 * 60 * 1000) {
  const router = useRouter()
  useEffect(() => {
    const id = setInterval(() => router.refresh(), intervalMs)
    return () => clearInterval(id)
  }, [router, intervalMs])
}

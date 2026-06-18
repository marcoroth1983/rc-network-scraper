import { useState, useEffect, useCallback } from 'react'
import type { AuthUser } from '../types/api'

export type { AuthUser }

export function useAuth() {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchUser = useCallback(() => {
    return fetch('/api/auth/me')
      .then(r => (r.ok ? r.json() : null))
      .then((data: AuthUser | null) => {
        setUser(data)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => {
    fetchUser()
  }, [fetchUser])

  const logout = async () => {
    await fetch('/api/auth/logout', { method: 'POST' })
    setUser(null)
    window.location.href = '/login'
  }

  return { user, loading, logout, reloadUser: fetchUser }
}

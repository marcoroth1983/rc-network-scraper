import { useState, useEffect, useCallback } from 'react'

export type AuthUser = {
  id: number;
  email: string;
  name: string | null;
  role: 'member' | 'admin';
  telegram_chat_id: number | null;
  telegram_linked_at: string | null;
}

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

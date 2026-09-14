import { useState, useEffect, useCallback } from 'react'

/**
 * Who is signed in. `user` is undefined while checking, null when signed out.
 * The backend keeps the login in an httpOnly cookie; this hook only mirrors it.
 */
export default function useAuth() {
  const [user, setUser] = useState(undefined)

  const refresh = useCallback(async () => {
    try {
      const response = await fetch('/api/auth/me')
      setUser(response.ok ? await response.json() : null)
    } catch {
      setUser(null)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const login = useCallback(async (username, password) => {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data.detail || `Sign-in failed (${response.status})`)
    setUser(data)
  }, [])

  const register = useCallback(async (username, email, password) => {
    const response = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, email, password }),
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data.detail || `Registration failed (${response.status})`)
    setUser(data)
  }, [])

  const logout = useCallback(async () => {
    await fetch('/api/auth/logout', { method: 'POST' })
    setUser(null)
  }, [])

  return { user, login, register, logout, refresh }
}

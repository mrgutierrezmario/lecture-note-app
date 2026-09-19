// Light / dark / system theme. The choice is per browser (localStorage) and
// applied as `data-theme` on <html>; "system" follows prefers-color-scheme and
// updates live when the OS setting changes.
import { useState, useEffect, useCallback } from 'react'

const STORAGE_KEY = 'theme'
const THEMES = ['system', 'light', 'dark']

const readStored = () => {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return THEMES.includes(value) ? value : 'system'
  } catch {
    return 'system'
  }
}

const systemQuery = () => window.matchMedia('(prefers-color-scheme: dark)')

const resolve = theme =>
  theme === 'system' ? (systemQuery().matches ? 'dark' : 'light') : theme

/**
 * Theme preference: 'system' | 'light' | 'dark'.
 *
 * The preference lives in localStorage (per browser, not a server setting) and
 * is applied as `data-theme="light|dark"` on <html>, which is what index.css
 * keys its tokens off. index.html runs the same resolution inline before first
 * paint so there is no flash; this hook keeps it in sync afterwards.
 */
export default function useTheme() {
  const [theme, setThemeState] = useState(readStored)

  useEffect(() => {
    const apply = () => { document.documentElement.dataset.theme = resolve(theme) }
    apply()
    if (theme !== 'system') return
    const query = systemQuery()
    query.addEventListener('change', apply)
    return () => query.removeEventListener('change', apply)
  }, [theme])

  const setTheme = useCallback(next => {
    if (!THEMES.includes(next)) return
    setThemeState(next)
    try {
      if (next === 'system') localStorage.removeItem(STORAGE_KEY)
      else localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // Private mode or blocked storage: the choice still applies for this page load.
    }
  }, [])

  return { theme, setTheme, resolved: resolve(theme) }
}

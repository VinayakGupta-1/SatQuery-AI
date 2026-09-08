import { useCallback, useEffect, useState } from 'react'

/**
 * State persisted in `localStorage`.
 *
 * Every access is guarded: private browsing, disabled site data and quota
 * exhaustion all throw, and none of them should take a screen down. When
 * storage is unavailable this degrades to ordinary component state.
 */
export function useLocalStorage<T>(
  key: string,
  initial: T,
): [T, (value: T | ((previous: T) => T)) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = window.localStorage.getItem(key)
      return raw === null ? initial : (JSON.parse(raw) as T)
    } catch {
      return initial
    }
  })

  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value))
    } catch {
      // Nothing to do: the value still holds for this page lifetime.
    }
  }, [key, value])

  const update = useCallback((next: T | ((previous: T) => T)) => {
    setValue(next)
  }, [])

  return [value, update]
}

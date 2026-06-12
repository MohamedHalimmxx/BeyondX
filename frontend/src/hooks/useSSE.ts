import { useState, useCallback, useRef } from 'react'

export type StageStatus = 'pending' | 'running' | 'done' | 'warning'

export interface Stage {
  stage: number
  name: string
  detail?: string
  status: StageStatus
  duration_ms?: number
}

export interface SSEState {
  status: 'idle' | 'running' | 'complete' | 'error'
  run_id: string | null
  stages: Stage[]
  result: Record<string, unknown> | null
  error: string | null
}

export function useSSE(totalStages: number) {
  const [state, setState] = useState<SSEState>({
    status: 'idle',
    run_id: null,
    stages: Array.from({ length: totalStages }, (_, i) => ({
      stage: i + 1,
      name: '',
      status: 'pending',
    })),
    result: null,
    error: null,
  })

  const abortRef = useRef<AbortController | null>(null)

  const run = useCallback(async (url: string, body: Record<string, unknown>) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setState(s => ({ ...s, status: 'running', error: null, result: null }))

    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      })

      if (!res.body) throw new Error('No response body')
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const messages = buffer.split('\n\n')
        buffer = messages.pop() ?? ''

        for (const msg of messages) {
          const lines = msg.trim().split('\n')
          let event = ''
          let data = ''
          for (const line of lines) {
            if (line.startsWith('event: ')) event = line.slice(7)
            if (line.startsWith('data: ')) data = line.slice(6)
          }
          if (!event || !data) continue

          try {
            const payload = JSON.parse(data)
            handleEvent(event, payload)
          } catch {
            // ignore parse errors
          }
        }
      }
    } catch (err: unknown) {
      if ((err as Error).name === 'AbortError') return
      setState(s => ({ ...s, status: 'error', error: String(err) }))
    }
  }, [])

  function handleEvent(event: string, payload: Record<string, unknown>) {
    switch (event) {
      case 'start':
        setState(s => ({ ...s, run_id: payload.run_id as string }))
        break

      case 'stage_start':
        setState(s => ({
          ...s,
          stages: s.stages.map(st =>
            st.stage === (payload.stage as number)
              ? { ...st, name: payload.name as string, detail: payload.detail as string, status: 'running' }
              : st
          ),
        }))
        break

      case 'stage_done':
        setState(s => ({
          ...s,
          stages: s.stages.map(st =>
            st.stage === (payload.stage as number)
              ? { ...st, name: payload.name as string, status: 'done', duration_ms: payload.duration_ms as number }
              : st
          ),
        }))
        break

      case 'stage_warning':
        setState(s => ({
          ...s,
          stages: s.stages.map(st =>
            st.stage === (payload.stage as number)
              ? { ...st, name: payload.name as string, status: 'warning' }
              : st
          ),
        }))
        break

      case 'complete':
        setState(s => ({ ...s, status: 'complete', result: payload }))
        break

      case 'error':
        setState(s => ({ ...s, status: 'error', error: payload.message as string }))
        break
    }
  }

  const reset = useCallback(() => {
    abortRef.current?.abort()
    setState({
      status: 'idle',
      run_id: null,
      stages: Array.from({ length: totalStages }, (_, i) => ({
        stage: i + 1,
        name: '',
        status: 'pending',
      })),
      result: null,
      error: null,
    })
  }, [totalStages])

  return { state, run, reset }
}
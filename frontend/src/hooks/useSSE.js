import { useEffect, useRef, useState, useCallback } from 'react'

/**
 * SSE 流式连接 Hook
 * @param {string} url - SSE 端点
 * @param {object} options - 配置项
 * @returns {{ data, done, error, connect, disconnect }}
 */
export default function useSSE(url, options = {}) {
  const { body = null, maxRetries = 3 } = options
  const [data, setData] = useState(null)
  const [done, setDone] = useState(false)
  const [error, setError] = useState(null)
  const sourceRef = useRef(null)
  const retryCount = useRef(0)

  const disconnect = useCallback(() => {
    if (sourceRef.current) {
      sourceRef.current.close()
      sourceRef.current = null
    }
    setDone(true)
  }, [])

  const connect = useCallback(() => {
    disconnect()
    setData(null)
    setDone(false)
    setError(null)
    retryCount.current = 0

    // 使用 Fetch API 处理 SSE（支持 POST + body）
    const controller = new AbortController()
    const init = {
      signal: controller.signal,
      headers: { 'Accept': 'text/event-stream' },
    }
    if (body) {
      init.method = 'POST'
      init.headers['Content-Type'] = 'application/json'
      init.body = typeof body === 'string' ? body : JSON.stringify(body)
    }

    fetch(url, init)
      .then(res => {
        if (!res.ok) throw new Error(`SSE HTTP ${res.status}`)
        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        const read = () => {
          reader.read().then(({ done: streamDone, value }) => {
            if (streamDone) {
              setDone(true)
              return
            }
            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split('\n')
            buffer = lines.pop() // 保留未完整的一行

            for (const line of lines) {
              if (line.startsWith('data: ')) {
                const payload = line.slice(6)
                if (payload === '[DONE]') {
                  setDone(true)
                  return
                }
                try {
                  const parsed = JSON.parse(payload)
                  setData(prev => {
                    // 合并 progress 更新
                    if (parsed.stage && parsed.pct !== undefined) {
                      return { ...(prev || {}), ...parsed, _raw: payload }
                    }
                    return parsed
                  })
                } catch {
                  // 非 JSON，当作纯文本
                  setData(payload)
                }
              } else if (line.startsWith('event: ')) {
                // 自定义事件类型，可扩展
              } else if (line === 'retry:') {
                // 重试指令
              }
            }
            read()
          }).catch(err => {
            if (err.name !== 'AbortError') {
              setError(err.message)
              setDone(true)
            }
          })
        }
        read()
      })
      .catch(err => {
        setError(err.message)
        setDone(true)
      })

    sourceRef.current = { close: () => controller.abort() }
  }, [url, body, disconnect])

  useEffect(() => () => disconnect(), [disconnect])

  return { data, done, error, connect, disconnect }
}

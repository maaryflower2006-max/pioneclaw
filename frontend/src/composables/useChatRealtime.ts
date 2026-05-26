import type { StreamRealtimeMessage } from '@/types/chat'
import { createChatTaskStreamUrl, getChatTask, cancelChatTask } from '@/api/chatTasks'

interface UseChatRealtimeOptions {
  dispatchStreamEvent: (message: StreamRealtimeMessage) => void
  getCurrentSessionId: () => string | null
  cacheSessionMessages: (sessionId: string) => void
  getLastProcessedChunkIndex: () => number
  updateLastProcessedChunkIndex: (index: number) => void
  onError?: (message: string) => void
}

/**
 * 高频事件类型集合 —— 这些事件会触发防抖缓存
 */
const highFrequencyCacheEventTypes = new Set([
  'content',
  'reasoning_chunk',
  'thinking',
  'tool_progress',
])

export function useChatRealtime(options: UseChatRealtimeOptions) {
  const cacheDebounceMs = 250
  let cacheTimer: number | null = null
  let pendingCacheSessionId: string | null = null
  let activeStreamSessionId: string | null = null

  // 取消机制：防止旧的 startTaskStream 实例干扰新流
  let isCancelled = false
  let activeTaskId: string | null = null
  let currentAbortController: AbortController | null = null

  const clearPendingCacheTimer = () => {
    if (cacheTimer !== null) {
      window.clearTimeout(cacheTimer)
      cacheTimer = null
    }
  }

  const flushCachedSession = () => {
    if (!pendingCacheSessionId) return
    options.cacheSessionMessages(pendingCacheSessionId)
    pendingCacheSessionId = null
  }

  const cancelActiveStream = async () => {
    isCancelled = true
    // 立即中止正在进行的 Fetch 流
    currentAbortController?.abort()
    currentAbortController = null
    // 通知服务端取消任务
    if (activeTaskId) {
      try {
        await cancelChatTask(activeTaskId)
      } catch { /* ignore */ }
    }
    activeTaskId = null
    clearPendingCacheTimer()
    flushCachedSession()
  }

  const scheduleSessionCache = (sessionId: string) => {
    pendingCacheSessionId = sessionId
    if (cacheTimer !== null) return
    cacheTimer = window.setTimeout(() => {
      cacheTimer = null
      flushCachedSession()
    }, cacheDebounceMs)
  }

  const persistSessionCache = (sessionId: string, immediate = false) => {
    if (immediate) {
      pendingCacheSessionId = sessionId
      clearPendingCacheTimer()
      flushCachedSession()
      return
    }
    scheduleSessionCache(sessionId)
  }

  /**
   * 处理单个 SSE 事件消息
   */
  const handleStreamEvent = (data: StreamRealtimeMessage) => {
    // 已取消的流实例不再分发事件，避免旧流干扰新流
    if (isCancelled) return

    // DEBUG: 记录所有收到的 SSE 事件
    // eslint-disable-next-line no-console
    console.log('[SSE] event type:', data.type, 'data:', JSON.stringify(data).slice(0, 200))

    // 跨会话保护：如果当前选中的会话已不是本流的目标会话，丢弃事件
    const currentSessionId = options.getCurrentSessionId()
    if (activeStreamSessionId && currentSessionId && activeStreamSessionId !== currentSessionId) {
      return
    }

    // 防御性去重：已处理过的 chunk 不再分发
    if (data._chunk_index !== undefined && data._chunk_index <= options.getLastProcessedChunkIndex()) {
      console.log('[SSE] ignore duplicated chunk:', data._chunk_index)
      return
    }

    if (data.type === 'error') {
      // 错误事件也要停止 streaming，避免 UI 一直卡在 loading
      options.dispatchStreamEvent({ type: 'stop_streaming' })
      options.onError?.(data.message || '发生错误')
      // 立即 flush 缓存，保证持久化状态结束在非 streaming
      if (currentSessionId || activeStreamSessionId) {
        persistSessionCache((currentSessionId || activeStreamSessionId)!, true)
      }
      return
    }

    // 所有非错误事件都分发给 reducer
    options.dispatchStreamEvent(data)

    // 持久化最新 chunk index，用于刷新后恢复 offset
    if (data._chunk_index !== undefined && activeTaskId) {
      try {
        sessionStorage.setItem(`pioneclaw_task_offset_${activeTaskId}`, String(data._chunk_index))
        options.updateLastProcessedChunkIndex(data._chunk_index)
      } catch { /* ignore storage failures */ }
    }

    // 会话缓存（高频事件防抖）
    if (currentSessionId) {
      const isHighFreq = highFrequencyCacheEventTypes.has(data.type)
      persistSessionCache(currentSessionId, !isHighFreq)
    }
  }

  /**
   * 启动 SSE 流并逐事件处理
   */
  async function startStream(
    url: string,
    body: Record<string, any>,
    token: string,
    onComplete?: () => void
  ): Promise<void> {
    // 绑定本次流式请求的目标会话，防止切换会话后旧请求串流
    activeStreamSessionId = body.session_id || null
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      const err = await response.text()
      throw new Error(`请求失败 (${response.status}): ${err}`)
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('无法读取响应流')
    }

    const decoder = new TextDecoder()
    let sseBuffer = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        sseBuffer += decoder.decode(value, { stream: true })
        const lines = sseBuffer.split('\n')
        sseBuffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const dataStr = line.slice(6)
          if (dataStr === '[DONE]') continue

          try {
            const data = JSON.parse(dataStr)
            handleStreamEvent(data)
          } catch {
            // 忽略 JSON 解析错误
          }
        }
      }
    } finally {
      reader.releaseLock()
      // 确保最终缓存被写入
      const sessionId = options.getCurrentSessionId()
      if (sessionId) {
        persistSessionCache(sessionId, true)
      }
      activeStreamSessionId = null
      onComplete?.()
    }
  }

  /**
   * 启动基于 task 的 SSE 流，支持自动重连
   */
  async function startTaskStream(
    taskId: string,
    token: string,
    onComplete?: () => void,
  ): Promise<void> {
    // 取消旧流，防止并发流冲突
    isCancelled = false
    activeTaskId = taskId

    const MAX_RECONNECT_ATTEMPTS = 10
    const BASE_RECONNECT_DELAY_MS = 1000
    let reconnectAttempts = 0
    let shouldReconnect = true

    // 尝试恢复上次收到的 chunk offset，避免刷新后重复接收已显示内容
    let lastChunkIndex = -1
    try {
      const savedOffset = sessionStorage.getItem(`pioneclaw_task_offset_${taskId}`)
      if (savedOffset !== null) {
        lastChunkIndex = parseInt(savedOffset, 10)
      }
    } catch { /* ignore */ }

    const tryConnect = async (): Promise<boolean> => {
      const url = createChatTaskStreamUrl(taskId, lastChunkIndex + 1)

      // 每次连接使用新的 AbortController，支持外部取消
      currentAbortController?.abort()
      currentAbortController = new AbortController()

      const response = await fetch(url, {
        method: 'GET',
        headers: {
          Authorization: `Bearer ${token}`,
        },
        signal: currentAbortController.signal,
      })

      if (!response.ok) {
        if (response.status === 410) {
          // 任务已过期，尝试从 REST API 获取结果
          try {
            const task = await getChatTask(taskId)
            if (task.status === 'completed' && task.final_response) {
              handleStreamEvent({
                type: 'done',
                response: task.final_response,
                thinking_content: task.thinking_content,
                input_tokens: task.input_tokens,
                output_tokens: task.output_tokens,
                latency_ms: task.latency_ms,
              } as StreamRealtimeMessage)
            } else if (task.error_message) {
              handleStreamEvent({
                type: 'error',
                message: task.error_message,
              } as StreamRealtimeMessage)
            } else if (task.status === 'running' || task.status === 'queued') {
              handleStreamEvent({
                type: 'error',
                message: '任务输出缓存已丢失，无法恢复',
              } as StreamRealtimeMessage)
            } else {
              handleStreamEvent({
                type: 'error',
                message: '任务已过期，无法恢复',
              } as StreamRealtimeMessage)
            }
          } catch (e) {
            handleStreamEvent({
              type: 'error',
              message: '任务已过期，无法恢复',
            } as StreamRealtimeMessage)
          }
          return false // 不再重连
        }
        throw new Error(`请求失败 (${response.status})`)
      }

      const reader = response.body?.getReader()
      if (!reader) throw new Error('无法读取响应流')

      const decoder = new TextDecoder()
      let sseBuffer = ''

      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          sseBuffer += decoder.decode(value, { stream: true })
          const lines = sseBuffer.split('\n')
          sseBuffer = lines.pop() || ''

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue
            const dataStr = line.slice(6)
            if (dataStr === '[DONE]') continue

            try {
              const data = JSON.parse(dataStr)

              // 更新 lastChunkIndex（如果 chunk 有序列号）
              if (data._chunk_index !== undefined) {
                lastChunkIndex = data._chunk_index
              }

              handleStreamEvent(data)

              // 检测完成
              if (data.type === 'done') {
                return false // 正常结束，不再重连
              }
            } catch {
              // 忽略 JSON 解析错误
            }
          }
        }
      } finally {
        reader.releaseLock()
      }

      // 流结束但没有 done 事件：可能是连接断开，需要重连
      return true
    }

    // 重连循环
    while (shouldReconnect && reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
      try {
        shouldReconnect = await tryConnect()
        if (!shouldReconnect) {
          reconnectAttempts = 0 // 正常结束，重置重连计数
        }
      } catch (error: any) {
        // 主动取消（AbortController）或被废弃的流实例，不再重连
        if (isCancelled || error.name === 'AbortError') {
          shouldReconnect = false
          break
        }
        console.error('[TaskStream] error:', error)
        reconnectAttempts++
        if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
          const delay = BASE_RECONNECT_DELAY_MS * Math.pow(2, reconnectAttempts - 1)
          await new Promise((r) => setTimeout(r, Math.min(delay, 30000)))
        }
      }
    }

    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      handleStreamEvent({
        type: 'error',
        message: '连接已断开，请刷新页面重试',
      } as StreamRealtimeMessage)
    }

    // 清理 offset 缓存
    try {
      sessionStorage.removeItem(`pioneclaw_task_offset_${taskId}`)
    } catch { /* ignore */ }

    onComplete?.()
  }

  return {
    startStream,
    startTaskStream,
    handleStreamEvent,
    cancelActiveStream,
  }
}

import { api } from './index'

export interface CreateChatTaskRequest {
  message: string
  context?: Array<{ role: string; content: string }>
  model_config_id?: number | null
  max_iterations?: number
  enable_tools?: boolean
  session_id?: string | null
  fast_mode?: boolean
}

export interface CreateChatTaskResponse {
  success: boolean
  task_id: string
  status: string
  position?: number
  message?: string
}

export interface ChatTaskDetail {
  task_id: string
  session_id: string | null
  status: string
  final_response: string | null
  thinking_content: string | null
  tool_calls: Array<Record<string, unknown>> | null
  input_tokens: number
  output_tokens: number
  latency_ms: number
  iterations: number
  error_message: string | null
  created_at: string | null
  started_at: string | null
  completed_at: string | null
}

export async function createChatTask(
  request: CreateChatTaskRequest,
): Promise<CreateChatTaskResponse> {
  const res = await api.post('/chat/react/tasks', request)
  return res.data
}

export async function getChatTask(taskId: string): Promise<ChatTaskDetail> {
  const res = await api.get(`/chat/react/tasks/${taskId}`)
  return res.data
}

export async function cancelChatTask(taskId: string): Promise<{ success: boolean; message: string }> {
  const res = await api.post(`/chat/react/tasks/${taskId}/cancel`)
  return res.data
}

export function createChatTaskStreamUrl(taskId: string, offset: number = 0): string {
  return `/api/chat/react/tasks/${taskId}/stream?offset=${offset}`
}

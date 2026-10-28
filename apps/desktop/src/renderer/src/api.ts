import type {
  AppConfig,
  Entity,
  KbKind,
  Message,
  Overview,
  Project,
  SearchHit,
  Session,
  Skill,
  TreeNode
} from './types'

const BASE = 'http://127.0.0.1:8787/api'

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {})
    }
  })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || `请求失败：${response.status}`)
  }
  return (await response.json()) as T
}

export const api = {
  listProjects: () => http<Project[]>('/projects'),
  createProject: (body: { name: string; title?: string; author?: string }) =>
    http<Project>('/projects', { method: 'POST', body: JSON.stringify(body) }),
  getProject: (projectId: string) => http<Project>(`/projects/${projectId}`),
  overview: (projectId: string) => http<Overview>(`/projects/${projectId}/overview`),

  listSessions: (projectId: string) => http<Session[]>(`/projects/${projectId}/sessions`),
  createSession: (projectId: string, title = '新会话', kind = 'main') =>
    http<Session>(`/projects/${projectId}/sessions`, {
      method: 'POST',
      body: JSON.stringify({ title, kind })
    }),
  deleteSession: (sessionId: string) =>
    http<{ ok: boolean }>(`/sessions/${sessionId}`, { method: 'DELETE' }),
  messages: (sessionId: string) => http<Message[]>(`/sessions/${sessionId}/messages`),

  entities: (projectId: string, kind: KbKind) =>
    http<Entity[]>(`/projects/${projectId}/kb/${kind}`),
  entity: (projectId: string, kind: KbKind, entityId: string) =>
    http<Entity>(`/projects/${projectId}/kb/${kind}/${entityId}`),
  saveEntity: (projectId: string, kind: KbKind, body: { id: string; meta: Record<string, unknown>; body: string }) =>
    http<Entity>(`/projects/${projectId}/kb/${kind}`, {
      method: 'POST',
      body: JSON.stringify(body)
    }),
  deleteEntity: (projectId: string, kind: KbKind, entityId: string) =>
    http<{ ok: boolean }>(`/projects/${projectId}/kb/${kind}/${entityId}`, {
      method: 'DELETE'
    }),
  search: (projectId: string, query: string) =>
    http<{ query: string; results: SearchHit[] }>(`/projects/${projectId}/search`, {
      method: 'POST',
      body: JSON.stringify({ query, top_k: 8 })
    }),
  reindex: (projectId: string) =>
    http<{ chunks: number; embedded: number }>(`/projects/${projectId}/reindex`, {
      method: 'POST'
    }),

  tree: (projectId: string) => http<TreeNode[]>(`/projects/${projectId}/tree`),
  skills: (projectId: string) => http<Skill[]>(`/projects/${projectId}/skills`),
  readFile: (projectId: string, path: string) =>
    http<{ path: string; content: string }>(
      `/projects/${projectId}/file?path=${encodeURIComponent(path)}`
    ),
  writeFile: (projectId: string, path: string, content: string) =>
    http<{ ok: boolean }>(`/projects/${projectId}/file`, {
      method: 'PUT',
      body: JSON.stringify({ path, content })
    }),
  gitDiff: (projectId: string) =>
    http<{ diff: string }>(`/projects/${projectId}/git/diff`),
  gitStatus: (projectId: string) =>
    http<{ status: string }>(`/projects/${projectId}/git/status`),

  getConfig: () => http<AppConfig>('/config'),
  saveConfig: (config: AppConfig) =>
    http<AppConfig>('/config', { method: 'PUT', body: JSON.stringify(config) })
}

interface StreamHandlers {
  onToken: (text: string) => void
  onToolStart: (name: string, input: string) => void
  onToolEnd: (name: string, output: string) => void
  onDone: () => void
  onError: (message: string) => void
}

export async function streamChat(
  sessionId: string,
  message: string,
  style: string,
  mode: 'main' | 'side',
  handlers: StreamHandlers
): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, message, style, mode })
    })
  } catch (error) {
    handlers.onError(`无法连接后端：${(error as Error).message}`)
    handlers.onDone()
    return
  }

  if (!response.ok || !response.body) {
    handlers.onError(`对话请求失败：${response.status}`)
    handlers.onDone()
    return
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')

    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      const raw = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      dispatchEvent(raw, handlers)
      boundary = buffer.indexOf('\n\n')
    }
  }
  handlers.onDone()
}

function dispatchEvent(raw: string, handlers: StreamHandlers): void {
  let event = 'message'
  const dataLines: string[] = []
  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }
  if (!dataLines.length) return
  let payload: Record<string, unknown>
  try {
    payload = JSON.parse(dataLines.join('\n')) as Record<string, unknown>
  } catch {
    return
  }
  switch (event) {
    case 'token':
      handlers.onToken(String(payload.text ?? ''))
      break
    case 'tool_start':
      handlers.onToolStart(String(payload.name ?? 'tool'), String(payload.input ?? ''))
      break
    case 'tool_end':
      handlers.onToolEnd(String(payload.name ?? 'tool'), String(payload.output ?? ''))
      break
    case 'error':
      handlers.onError(String(payload.message ?? '未知错误'))
      break
  }
}

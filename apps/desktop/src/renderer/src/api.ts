import type {
  AppConfig,
  ApprovalBundle,
  ApprovalDecision,
  ApprovalRecord,
  McpServerStatus,
  LintReport,
  ChunkItem,
  ContextBundle,
  Entity,
  Expert,
  KbConfig,
  KbKind,
  KnowledgeBaseSummary,
  MemoryState,
  Message,
  Overview,
  Project,
  ReferenceItem,
  SearchHit,
  Session,
  SessionPermission,
  Skill,
  TreeNode,
  TurnChanges
} from './types'

let API_BASE = 'http://127.0.0.1:8787/api'

export function setApiBase(port: number): void {
  API_BASE = `http://127.0.0.1:${port}/api`
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
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

interface SearchOptions {
  kinds?: KbKind[]
  chapter_limit?: number | null
  top_k?: number
  threshold?: number
  mode?: 'hybrid' | 'keyword' | 'vector'
  alpha?: number
}

export const api = {
  listProjects: () => http<Project[]>('/projects'),
  lint: (projectId: string) => http<LintReport>(`/projects/${projectId}/lint`),
  mcpStatus: () => http<{ servers: McpServerStatus[] }>('/mcp/status'),
  mcpReload: () => http<{ servers: McpServerStatus[] }>('/mcp/reload', { method: 'POST' }),
  projectApprovals: (projectId: string, status: string) =>
    http<ApprovalRecord[]>(
      `/projects/${projectId}/approvals?status=${encodeURIComponent(status)}&limit=100`
    ),
  createProject: (body: { name: string; title?: string; author?: string; path?: string }) =>
    http<Project>('/projects', { method: 'POST', body: JSON.stringify(body) }),
  defaultPath: (name: string) =>
    http<{ path: string }>(`/projects/default-path?name=${encodeURIComponent(name)}`),
  openProject: (path: string) =>
    http<Project>('/projects/open', { method: 'POST', body: JSON.stringify({ path }) }),
  getProject: (projectId: string) => http<Project>(`/projects/${projectId}`),
  overview: (projectId: string) => http<Overview>(`/projects/${projectId}/overview`),

  listSessions: (projectId: string) => http<Session[]>(`/projects/${projectId}/sessions`),
  createSession: (
    projectId: string,
    options: {
      title?: string
      kind?: string
      expertId?: string
      domain?: string
      permissionMode?: SessionPermission
    } = {}
  ) =>
    http<Session>(`/projects/${projectId}/sessions`, {
      method: 'POST',
      body: JSON.stringify({
        title: options.title ?? '新会话',
        kind: options.kind ?? 'main',
        expert_id: options.expertId ?? null,
        domain: options.domain ?? 'book',
        permission_mode: options.permissionMode ?? null
      })
    }),
  updateSession: (
    sessionId: string,
    patch: {
      title?: string
      expert_id?: string | null
      domain?: string
      permission_mode?: SessionPermission
    }
  ) =>
    http<Session>(`/sessions/${sessionId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch)
    }),
  context: (sessionId: string) => http<ContextBundle>(`/sessions/${sessionId}/context`),
  distill: (sessionId: string) =>
    http<{ ok: boolean; added: number; message?: string; items?: string[] }>(
      `/sessions/${sessionId}/distill`,
      { method: 'POST' }
    ),
  memory: (projectId?: string) =>
    http<MemoryState>(`/memory${projectId ? `?project_id=${projectId}` : ''}`),
  saveMemory: (scope: string, content: string, projectId?: string) =>
    http<unknown>(`/memory/${scope}`, {
      method: 'PUT',
      body: JSON.stringify({ content, project_id: projectId ?? null })
    }),
  deleteMemoryEntry: (scope: string, text: string, projectId?: string) =>
    http<{ ok: boolean }>('/memory/delete', {
      method: 'POST',
      body: JSON.stringify({ scope, text, project_id: projectId ?? null })
    }),
  deleteSession: (sessionId: string) =>
    http<{ ok: boolean }>(`/sessions/${sessionId}`, { method: 'DELETE' }),
  messages: (sessionId: string) => http<Message[]>(`/sessions/${sessionId}/messages`),
  pending: (sessionId: string) =>
    http<{ approval: ApprovalBundle | null }>(`/sessions/${sessionId}/pending`),
  steer: (sessionId: string, message: string) =>
    http<{ ok: boolean; queued: number }>('/chat/steer', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, message })
    }),
  approvals: (sessionId: string) =>
    http<ApprovalBundle[]>(`/sessions/${sessionId}/approvals`),
  referenceCandidates: (projectId: string, q: string, limit = 20) =>
    http<{ items: ReferenceItem[] }>(
      `/projects/${projectId}/reference-candidates?q=${encodeURIComponent(q)}&limit=${limit}`
    ),

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
  search: (projectId: string, query: string, options: SearchOptions = {}) =>
    http<{ query: string; results: SearchHit[] }>(`/projects/${projectId}/search`, {
      method: 'POST',
      body: JSON.stringify({ query, top_k: 8, ...options })
    }),
  reindex: (projectId: string) =>
    http<{ chunks: number; embedded: number }>(`/projects/${projectId}/reindex`, {
      method: 'POST'
    }),

  knowledgeBases: (projectId: string) =>
    http<{ items: KnowledgeBaseSummary[]; index: { chunks: number; embedded: number }; config: KbConfig }>(
      `/projects/${projectId}/knowledge-bases`
    ),
  chunks: (projectId: string, kind?: string, limit = 50, offset = 0) =>
    http<{ total: number; items: ChunkItem[] }>(
      `/projects/${projectId}/chunks?limit=${limit}&offset=${offset}${kind ? `&kind=${kind}` : ''}`
    ),
  kbConfig: (projectId: string) => http<KbConfig>(`/projects/${projectId}/kb-config`),
  saveKbConfig: (projectId: string, config: KbConfig) =>
    http<KbConfig>(`/projects/${projectId}/kb-config`, {
      method: 'PUT',
      body: JSON.stringify(config)
    }),

  experts: (projectId: string) => http<Expert[]>(`/projects/${projectId}/experts`),
  saveExpert: (
    projectId: string,
    expertId: string,
    body: { id: string; meta: Record<string, unknown>; body: string }
  ) =>
    http<Expert>(`/projects/${projectId}/experts/${expertId}`, {
      method: 'PUT',
      body: JSON.stringify(body)
    }),
  deleteExpert: (projectId: string, expertId: string) =>
    http<{ ok: boolean }>(`/projects/${projectId}/experts/${expertId}`, {
      method: 'DELETE'
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
  onContext?: (bundle: ContextBundle) => void
  onApproval?: (approval: ApprovalBundle) => void
  onToken: (text: string) => void
  onToolStart: (name: string, input: string) => void
  onToolEnd: (name: string, output: string) => void
  onDone: (payload?: { elapsed_ms?: number; changes?: TurnChanges }) => void
  onError: (message: string) => void
}

export interface StreamHandlerSet extends StreamHandlers {}

export async function streamChat(
  sessionId: string,
  message: string,
  mode: 'main' | 'side' | 'expert_builder' | 'skill_builder',
  references: ReferenceItem[],
  handlers: StreamHandlers
): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        message,
        mode,
        references: references.length ? references : null
      })
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

  await consumeStream(response, handlers)
}

export async function approveChat(
  sessionId: string,
  decisions: ApprovalDecision[],
  handlers: StreamHandlers
): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}/chat/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, decisions })
    })
  } catch (error) {
    handlers.onError(`无法连接后端：${(error as Error).message}`)
    handlers.onDone()
    return
  }
  if (!response.ok || !response.body) {
    handlers.onError(`审批请求失败：${response.status}`)
    handlers.onDone()
    return
  }
  await consumeStream(response, handlers)
}

async function consumeStream(response: Response, handlers: StreamHandlers): Promise<void> {
  if (!response.body) {
    handlers.onError('响应没有内容')
    handlers.onDone()
    return
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let doneSeen = false

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')

    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      const raw = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      doneSeen = dispatchEvent(raw, handlers) || doneSeen
      boundary = buffer.indexOf('\n\n')
    }
  }
  if (!doneSeen) handlers.onDone()
}

function dispatchEvent(raw: string, handlers: StreamHandlers): boolean {
  let event = 'message'
  const dataLines: string[] = []
  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }
  if (!dataLines.length) return false
  let payload: Record<string, unknown>
  try {
    payload = JSON.parse(dataLines.join('\n')) as Record<string, unknown>
  } catch {
    return false
  }
  switch (event) {
    case 'context':
      handlers.onContext?.(payload as unknown as ContextBundle)
      break
    case 'approval':
      handlers.onApproval?.(payload as unknown as ApprovalBundle)
      break
    case 'token':
      handlers.onToken(String(payload.text ?? ''))
      break
    case 'tool_start':
      handlers.onToolStart(String(payload.name ?? 'tool'), String(payload.input ?? ''))
      break
    case 'tool_end':
      handlers.onToolEnd(String(payload.name ?? 'tool'), String(payload.output ?? ''))
      break
    case 'done':
      handlers.onDone(payload as { elapsed_ms?: number; changes?: TurnChanges })
      return true
    case 'error':
      handlers.onError(String(payload.message ?? '未知错误'))
      break
  }
  return false
}

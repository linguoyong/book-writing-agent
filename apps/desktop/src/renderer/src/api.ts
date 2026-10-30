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
  EmbeddingOption,
  EmbeddingProbe,
  EmbeddingSettings,
  Expert,
  GitChange,
  IndexJob,
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
let API_TOKEN = ''

export function setApiBase(port: number, token = ''): void {
  API_BASE = `http://127.0.0.1:${port}/api`
  API_TOKEN = token
}

/** 本地后端的访问令牌：由 Electron 主进程生成，经 IPC 下发，不写入磁盘 */
function authHeaders(): Record<string, string> {
  return API_TOKEN ? { 'X-Book-Agent-Token': API_TOKEN } : {}
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...(init?.headers ?? {})
    }
  })
  if (!response.ok) {
    const text = await response.text()
    let message = text
    try {
      const parsed = JSON.parse(text) as { detail?: unknown }
      if (typeof parsed.detail === 'string') message = parsed.detail
    } catch {
      /* 非 JSON 错误体，沿用原文 */
    }
    if (response.status === 401) {
      message = '本地后端拒绝了请求：缺少访问令牌，请从桌面应用启动'
    } else if (response.status === 404) {
      // 开发时最容易踩：界面热更新了，Python 后端还是旧进程
      message = `接口不存在（${path}）：本地后端可能是更新前的旧进程，重启一次应用后重试`
    }
    throw new Error(message || `请求失败：${response.status}`)
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
  deleteProject: (projectId: string, purge = false) =>
    http<{ ok: boolean }>(`/projects/${projectId}?purge=${purge}`, {
      method: 'DELETE'
    }),
  createProject: (body: {
    name: string
    title?: string
    author?: string
    path?: string
    words_per_chapter?: number
  }) =>
    http<Project>('/projects', { method: 'POST', body: JSON.stringify(body) }),
  defaultPath: (name: string) =>
    http<{ path: string }>(`/projects/default-path?name=${encodeURIComponent(name)}`),
  openProject: (path: string) =>
    http<Project>('/projects/open', { method: 'POST', body: JSON.stringify({ path }) }),
  getProject: (projectId: string) => http<Project>(`/projects/${projectId}`),
  overview: (projectId: string) => http<Overview>(`/projects/${projectId}/overview`),

  listSessions: (projectId: string) => http<Session[]>(`/projects/${projectId}/sessions`),
  allSessions: () => http<Session[]>('/sessions'),
  createSession: (
    projectId: string,
    options: {
      title?: string
      kind?: string
      expertId?: string
      domain?: string
      permissionMode?: SessionPermission
      modelId?: string
    } = {}
  ) =>
    http<Session>(`/projects/${projectId}/sessions`, {
      method: 'POST',
      body: JSON.stringify({
        title: options.title ?? '新会话',
        kind: options.kind ?? 'main',
        expert_id: options.expertId ?? null,
        domain: options.domain ?? 'book',
        permission_mode: options.permissionMode ?? null,
        model_id: options.modelId ?? null
      })
    }),
  updateSession: (
    sessionId: string,
    patch: {
      title?: string
      expert_id?: string | null
      domain?: string
      permission_mode?: SessionPermission
      model_id?: string | null
      archived?: boolean
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
    http<IndexJob>(`/projects/${projectId}/reindex`, { method: 'POST' }),
  indexStatus: (projectId: string) =>
    http<IndexJob>(`/projects/${projectId}/index/status`),
  gitCommit: (projectId: string, message: string) =>
    http<{ ok: boolean; message: string }>(`/projects/${projectId}/git/commit`, {
      method: 'POST',
      body: JSON.stringify({ message })
    }),

  knowledgeBases: (projectId: string) =>
    http<{
      items: KnowledgeBaseSummary[]
      index: {
        chunks: number
        embedded: number
        provider?: string
        model?: string
        dim?: number
        expected_dim?: number
        backend?: string
        error?: string
      }
      config: KbConfig
    }>(`/projects/${projectId}/knowledge-bases`),
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
  importStyle: (projectId: string, path: string) =>
    http<{
      expert: { id: string; name: string }
      skill: { id: string; name: string } | null
    }>(`/projects/${projectId}/import-style`, {
      method: 'POST',
      body: JSON.stringify({ path })
    }),
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
  readFile: (projectId: string, path: string, head?: number) =>
    http<{
      path: string
      kind: 'text' | 'image' | 'binary' | 'large'
      content?: string
      data_url?: string
      size?: number
      mtime?: number
      truncated?: boolean
    }>(
      `/projects/${projectId}/file?path=${encodeURIComponent(path)}${
        head ? `&head=${head}` : ''
      }`
    ),
  writeFile: (
    projectId: string,
    path: string,
    content: string,
    expectedMtime?: number
  ) =>
    http<{ ok: boolean; mtime: number }>(`/projects/${projectId}/file`, {
      method: 'PUT',
      body: JSON.stringify({ path, content, expected_mtime: expectedMtime ?? null })
    }),
  fsCreate: (projectId: string, path: string, kind: 'file' | 'dir' = 'file') =>
    http<{ ok: boolean }>(`/projects/${projectId}/fs/create`, {
      method: 'POST',
      body: JSON.stringify({ path, kind })
    }),
  fsRename: (projectId: string, path: string, newPath: string) =>
    http<{ ok: boolean }>(`/projects/${projectId}/fs/rename`, {
      method: 'POST',
      body: JSON.stringify({ path, new_path: newPath })
    }),
  fsDelete: (projectId: string, path: string) =>
    http<{ ok: boolean }>(`/projects/${projectId}/fs?path=${encodeURIComponent(path)}`, {
      method: 'DELETE'
    }),
  gitDiff: (projectId: string, path?: string) =>
    http<{ diff: string }>(
      `/projects/${projectId}/git/diff${path ? `?path=${encodeURIComponent(path)}` : ''}`
    ),
  gitChanges: (projectId: string) =>
    http<{ items: GitChange[] }>(`/projects/${projectId}/git/changes`),
  gitStatus: (projectId: string) =>
    http<{ status: string }>(`/projects/${projectId}/git/status`),

  getConfig: () => http<AppConfig>('/config'),
  saveConfig: (config: AppConfig) =>
    http<AppConfig>('/config', { method: 'PUT', body: JSON.stringify(config) }),
  embeddingOptions: () =>
    http<{ default: string; local: EmbeddingOption[] }>('/embeddings/options'),
  testEmbedding: (settings: EmbeddingSettings) =>
    http<EmbeddingProbe>('/embeddings/test', {
      method: 'POST',
      body: JSON.stringify({
        provider: settings.provider,
        base_url: settings.base_url,
        api_key: settings.api_key,
        model: settings.model,
        local_model: settings.local_model
      })
    })
}

interface StreamHandlers {
  onContext?: (bundle: ContextBundle) => void
  onApproval?: (approval: ApprovalBundle) => void
  onToken: (text: string) => void
  onToolStart: (name: string, input: string) => void
  onToolEnd: (name: string, output: string) => void
  onDone: (payload?: { elapsed_ms?: number; changes?: TurnChanges }) => void
  onError: (message: string) => void
  /** 用户主动中止：不再当作错误提示 */
  onAborted?: () => void
}

export interface StreamHandlerSet extends StreamHandlers {}

function isAbort(error: unknown): boolean {
  return (error as { name?: string } | null)?.name === 'AbortError'
}

export async function streamChat(
  sessionId: string,
  message: string,
  mode: 'main' | 'side' | 'expert_builder' | 'skill_builder',
  references: ReferenceItem[],
  handlers: StreamHandlers,
  signal?: AbortSignal,
  parentSessionId?: string
): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({
        session_id: sessionId,
        message,
        mode,
        references: references.length ? references : null,
        parent_session_id: parentSessionId ?? null
      }),
      signal
    })
  } catch (error) {
    if (isAbort(error)) {
      handlers.onAborted?.()
      return
    }
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
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}/chat/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ session_id: sessionId, decisions }),
      signal
    })
  } catch (error) {
    if (isAbort(error)) {
      handlers.onAborted?.()
      return
    }
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

export async function regenerateChat(
  sessionId: string,
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}/sessions/${sessionId}/regenerate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      signal
    })
  } catch (error) {
    if (isAbort(error)) {
      handlers.onAborted?.()
      return
    }
    handlers.onError(`无法连接后端：${(error as Error).message}`)
    handlers.onDone()
    return
  }
  if (!response.ok || !response.body) {
    handlers.onError(`重新生成失败：${response.status}`)
    handlers.onDone()
    return
  }
  await consumeStream(response, handlers)
}

async function consumeStream(response: Response, handlers: StreamHandlers): Promise<void> {  if (!response.body) {
    handlers.onError('响应没有内容')
    handlers.onDone()
    return
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let doneSeen = false

  try {
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
  } catch (error) {
    if (isAbort(error)) {
      handlers.onAborted?.()
      return
    }
    handlers.onError(`流式读取中断：${(error as Error).message}`)
    handlers.onDone()
    return
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

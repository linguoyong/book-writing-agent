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
  ExtractCandidate,
  GitCommit,
  GitFileChange,
  ExtractStatus,
  ImportPreview,
  ImportResult,
  ExtractStats,
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
  PromptDetail,
  PromptLayerInfo,
  ReferenceItem,
  RunSnapshot,
  SearchHit,
  Session,
  SessionPermission,
  Skill,
  TreeNode,
  UsageSummary,
  ModelPrice,
  GraphData,
  TimelineData,
  MaterialResult,
  ReviewChapter,
  ReviewDetail,
  DeconstructStatus
} from './types'

let API_BASE = 'http://127.0.0.1:8787/api'

/**
 * 只设置端口。访问令牌由主进程在 `webRequest.onBeforeSendHeaders` 里注入，
 * 渲染层拿不到、也不需要知道它。
 */
export function setApiBase(port: number): void {
  API_BASE = `http://127.0.0.1:${port}/api`
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number
  ) {
    super(message)
    this.name = 'ApiError'
  }
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
    const text = await response.text()
    let detail = ''
    try {
      const parsed = JSON.parse(text) as { detail?: unknown }
      if (typeof parsed.detail === 'string') detail = parsed.detail
    } catch {
      /* 非 JSON 错误体，沿用原文 */
    }
    let message = detail || text
    if (response.status === 401) {
      message = '本地后端拒绝了请求：缺少访问令牌，请从桌面应用启动'
    } else if (response.status === 404 && (!detail || detail === 'Not Found')) {
      // 只有「路由本身不存在」才这么猜；业务上的 404（空间/会话不存在）保留原文
      message = `接口不存在（${path}）：本地后端可能是更新前的旧进程，重启一次应用后重试`
    }
    throw new ApiError(message || `请求失败：${response.status}`, response.status)
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
  sessionRun: (sessionId: string) => http<RunSnapshot>(`/sessions/${sessionId}/run`),
  prompts: (projectId?: string | null) =>
    http<{ items: PromptLayerInfo[] }>(
      `/prompts${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`
    ),
  prompt: (layer: string, projectId?: string | null) =>
    http<PromptDetail>(
      `/prompts/${layer}${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`
    ),
  savePrompt: (layer: string, content: string, projectId?: string | null) =>
    http<{ ok: boolean; path: string }>(`/prompts/${layer}`, {
      method: 'PUT',
      body: JSON.stringify({ content, project_id: projectId ?? null })
    }),
  resetPrompt: (layer: string, projectId?: string | null) =>
    http<{ ok: boolean }>(
      `/prompts/${layer}/reset${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`,
      { method: 'POST' }
    ),
  stopRun: (sessionId: string) =>
    http<{ ok: boolean }>(`/sessions/${sessionId}/run/stop`, { method: 'POST' }),
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
  projectGraph: (projectId: string, includeMentions = true) =>
    http<GraphData>(
      `/projects/${projectId}/graph?include_mentions=${includeMentions}`
    ),
  projectTimeline: (projectId: string) =>
    http<TimelineData>(`/projects/${projectId}/timeline`),
  saveMaterial: (
    projectId: string,
    body: { text: string; title?: string; source?: string; tags?: string[] }
  ) =>
    http<MaterialResult>(`/projects/${projectId}/materials`, {
      method: 'POST',
      body: JSON.stringify(body)
    }),
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
  searchText: (
    projectId: string,
    body: {
      query: string
      scope?: string
      path?: string | null
      regex?: boolean
      ignore_case?: boolean
    }
  ) =>
    http<{
      total: number
      files: number
      truncated: boolean
      items: { path: string; line: number; snippet: string }[]
    }>(`/projects/${projectId}/text-search`, {
      method: 'POST',
      body: JSON.stringify(body)
    }),
  replaceText: (
    projectId: string,
    body: {
      query: string
      replacement: string
      scope?: string
      path?: string | null
      regex?: boolean
      ignore_case?: boolean
      dry_run?: boolean
    }
  ) =>
    http<{
      dry_run: boolean
      total: number
      files: number
      changed: { path: string; count: number }[]
      samples: { path: string; line: number; snippet: string }[]
    }>(`/projects/${projectId}/text-replace`, {
      method: 'POST',
      body: JSON.stringify(body)
    }),
  rewriteText: (
    projectId: string,
    body: { text: string; action: string; tone?: string; before?: string; after?: string }
  ) => http<{ text: string; action: string }>(`/projects/${projectId}/rewrite`, {
    method: 'POST',
    body: JSON.stringify(body)
  }),
  gitLog: (projectId: string, limit = 40) =>
    http<{ items: GitCommit[] }>(`/projects/${projectId}/git/log?limit=${limit}`),
  gitCommitFiles: (projectId: string, commit: string) =>
    http<{ items: GitFileChange[] }>(
      `/projects/${projectId}/git/files?commit=${encodeURIComponent(commit)}`
    ),
  gitFileDiff: (projectId: string, commit: string, path: string) =>
    http<{ path: string; diff: string }>(
      `/projects/${projectId}/git/file-diff?commit=${encodeURIComponent(commit)}&path=${encodeURIComponent(path)}`
    ),
  gitRestore: (projectId: string, commit: string, path: string) =>
    http<{ path: string; commit: string; restored_from: string; unchanged?: boolean }>(
      `/projects/${projectId}/git/restore`,
      { method: 'POST', body: JSON.stringify({ commit, path }) }
    ),
  newChapter: (projectId: string, title = '') =>
    http<{ path: string; chapter: number; volume: number; title: string }>(
      `/projects/${projectId}/chapter`,
      { method: 'POST', body: JSON.stringify({ title }) }
    ),
  projectUsage: (projectId: string, days = 14) =>
    http<UsageSummary>(`/projects/${projectId}/usage?days=${days}`),
  usagePricing: () =>
    http<{ pricing: Record<string, ModelPrice>; currency: string; unit: string }>(
      '/usage/pricing'
    ),
  saveUsagePricing: (pricing: Record<string, ModelPrice>) =>
    http<{ pricing: Record<string, ModelPrice>; currency: string }>('/usage/pricing', {
      method: 'PUT',
      body: JSON.stringify({ pricing })
    }),
  exportTxt: (projectId: string, path: string, includeToc = false) =>
    http<{
      path: string
      name: string
      chapters: number
      chars: number
      bytes: number
      encoding: string
      first: string
      last: string
    }>(`/projects/${projectId}/export/txt`, {
      method: 'POST',
      body: JSON.stringify({ path, encoding: 'utf-8', include_toc: includeToc })
    }),
  extractStatus: (projectId: string) =>
    http<ExtractStatus>(`/projects/${projectId}/extract/status`),
  extractPreview: (projectId: string, limit = 3) =>
    http<{ preview: ExtractStats; state: ExtractStatus['state'] }>(
      `/projects/${projectId}/extract/preview`,
      { method: 'POST', body: JSON.stringify({ limit, dry_run: true }) }
    ),
  extractStart: (projectId: string, limit = 0) =>
    http<{ started: boolean } & ExtractStatus>(`/projects/${projectId}/extract`, {
      method: 'POST',
      body: JSON.stringify({ limit, dry_run: false })
    }),
  extractCandidates: (projectId: string) =>
    http<{ total: number; items: ExtractCandidate[] }>(
      `/projects/${projectId}/extract/candidates`
    ),
  acceptCandidate: (projectId: string, candidateId: string) =>
    http<{ ok: boolean }>(
      `/projects/${projectId}/extract/candidates/${encodeURIComponent(candidateId)}/accept`,
      { method: 'POST' }
    ),
  rejectCandidate: (projectId: string, candidateId: string) =>
    http<{ ok: boolean }>(
      `/projects/${projectId}/extract/candidates/${encodeURIComponent(candidateId)}/reject`,
      { method: 'POST' }
    ),
  extractStop: (projectId: string) =>
    http<{ stopped: boolean }>(`/projects/${projectId}/extract/stop`, { method: 'POST' }),
  importPreview: (projectId: string, path: string, pattern = '') =>
    http<ImportPreview>(`/projects/${projectId}/import/preview`, {
      method: 'POST',
      body: JSON.stringify({ path, pattern })
    }),
  importBook: (
    projectId: string,
    path: string,
    excluded: number[],
    titles: Record<string, string>,
    pattern = ''
  ) =>
    http<ImportResult>(`/projects/${projectId}/import`, {
      method: 'POST',
      body: JSON.stringify({ path, pattern, excluded, titles })
    }),
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
    }),

  reviews: (projectId: string) => http<ReviewChapter[]>(`/projects/${projectId}/reviews`),
  review: (projectId: string, chapter: string) =>
    http<ReviewDetail>(`/projects/${projectId}/review?chapter=${encodeURIComponent(chapter)}`),
  runReview: (projectId: string, chapter: string, note = '') =>
    http<ReviewDetail>(`/projects/${projectId}/review`, {
      method: 'POST',
      body: JSON.stringify({ chapter, note })
    }),
  deconstructStart: (
    projectId: string,
    body: { source?: string; group_size?: number; max_groups?: number; create_expert?: boolean }
  ) =>
    http<{ started: boolean; source: string }>(`/projects/${projectId}/deconstruct`, {
      method: 'POST',
      body: JSON.stringify(body)
    }),
  deconstructStatus: (projectId: string) =>
    http<DeconstructStatus>(`/projects/${projectId}/deconstruct/status`),
  deconstructStop: (projectId: string) =>
    http<{ stopping: boolean }>(`/projects/${projectId}/deconstruct/stop`, { method: 'POST' })
}

interface StreamHandlers {
  onContext?: (bundle: ContextBundle) => void
  onApproval?: (approval: ApprovalBundle) => void
  onToken: (text: string) => void
  onToolStart: (name: string, input: string) => void
  onToolEnd: (name: string, output: string) => void
  onDone: (payload?: Partial<import('./types').TurnMeta>) => void
  onError: (message: string) => void
  /** 用户主动中止：不再当作错误提示 */
  onAborted?: () => void
}

export interface StreamHandlerSet extends StreamHandlers {}

/** 流式请求失败时优先展示后端 detail（如「当前会话还在生成…」），没有才回落到状态码。 */
async function streamFailure(response: Response, prefix: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === 'string' && body.detail.trim()) return body.detail
  } catch {
    /* 非 JSON 错误体 */
  }
  return `${prefix}：${response.status}`
}

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
      headers: { 'Content-Type': 'application/json' },
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
    handlers.onError(await streamFailure(response, '对话请求失败'))
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
      headers: { 'Content-Type': 'application/json' },
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
    handlers.onError(await streamFailure(response, '审批请求失败'))
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
      headers: { 'Content-Type': 'application/json' },
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
    handlers.onError(await streamFailure(response, '重新生成失败'))
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
  } finally {
    await reader.cancel().catch(() => undefined)
  }
  if (!doneSeen) {
    // 后端进程被杀 / 网络中断时流会「正常结束」但缺 done 事件，
    // 不能把半截文字当成完整回答。
    handlers.onError('生成中断：这次回答可能不完整，可以重新生成')
    handlers.onDone()
  }
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
      handlers.onDone(
        payload as Partial<import('./types').TurnMeta>
      )
      return true
    case 'error':
      handlers.onError(String(payload.message ?? '未知错误'))
      break
  }
  return false
}

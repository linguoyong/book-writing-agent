export interface BookMeta {
  title: string
  author: string
  synopsis: string
  progress: { volume: number; chapter: number }
}

export interface Project {
  id: string
  name: string
  path: string
  exists?: boolean
  meta?: BookMeta
  created_at: string
  updated_at: string
}

export interface Session {
  id: string
  project_id: string
  title: string
  kind: string
  expert_id?: string | null
  domain?: string | null
  permission_mode?: SessionPermission | null
  created_at: string
  updated_at: string
}

export interface TurnChanges {
  files: string[]
  diff: string
  truncated?: boolean
}

export interface TurnMeta {
  elapsed_ms: number
  changes: TurnChanges
}

export interface Message {
  id: number
  session_id: string
  role: 'user' | 'assistant'
  content: string
  meta?: {
    tool_calls?: { name: string; input: string }[]
    turn?: TurnMeta
    awaiting_approval?: boolean
    interrupted?: boolean
    steering?: boolean
    references?: ReferenceItem[]
  } | null
  created_at: string
}

export type KbKind =
  | 'characters'
  | 'factions'
  | 'items'
  | 'locations'
  | 'world'
  | 'outline'
  | 'materials'
  | 'styles'

export interface Entity {
  id: string
  kind: KbKind
  title: string
  meta: Record<string, unknown>
  body: string
  file: string
  updated_at?: number
}

export interface TreeNode {
  name: string
  path: string
  type: 'dir' | 'file'
  children?: TreeNode[]
}

export interface SearchHit {
  id: string
  kind: string
  ref: string
  title: string
  text: string
  chapter: number
  entities: string[]
  source: string
  /** 相对本轮最高分的 0-1 相关度，阈值按它过滤 */
  score: number
  /** 检索器原始分：BM25 / cosine / RRF，用于排查召回质量 */
  raw_score?: number
}

export interface Overview {
  book: BookMeta
  kb_counts: Record<string, number>
  chapter_count: number
  manuscript_count: number
  index: { chunks: number; embedded: number; provider: string }
  git_dirty: boolean
}

export interface Skill {
  name: string
  description: string
  path: string
  enabled: boolean
}

export interface Expert {
  id: string
  name: string
  description: string
  tags: string[]
  avatar: string
  prompt: string
  skills: string[]
  max_turns?: number
  body: string
  file: string
}

export interface ContextItem {
  layer: string
  title: string
  source: string
  chars: number
  limit: number
  truncated: boolean
  preview: string
  included: boolean
}

export interface CompactionPlan {
  window: number
  trigger: number
  truncate: number
  keep_messages: number
}

export interface ContextBundle {
  system_prompt: string
  items: ContextItem[]
  expert_id: string
  domain_id: string
  fingerprint: string
  total_chars: number
  model?: { name: string; context_window: number }
  compaction?: CompactionPlan
}

export interface MemoryFile {
  scope: string
  title: string
  path: string
  chars: number
  updated: number
  files?: string[]
}

export interface MemoryState {
  status: MemoryFile[]
  scopes: Record<string, string>
  entries?: Record<string, MemoryEntry[]>
  sources?: Record<string, string>
}

export interface MemoryEntry {
  text: string
  date?: string
  source?: string
}

export interface ApprovalRequest {
  name: string
  args: Record<string, unknown>
  raw_args?: Record<string, unknown>
  description: string
  target: string
  diff: string
  note: string
}

export type ApprovalDecision =
  | { type: 'approve' }
  | { type: 'reject'; message?: string }
  | { type: 'edit'; edited_action: { name: string; args: Record<string, unknown> } }

export interface ApprovalRecord {
  id: string
  session_id: string
  session_title: string
  status: 'pending' | 'approved' | 'rejected' | 'expired'
  created_at: string
  decided_at: string | null
  payload: { requests?: ApprovalRequest[] }
  decision: ApprovalDecision[]
}

export interface ApprovalBundle {
  approval_id: string
  interrupt_id?: string | null
  requests: ApprovalRequest[]
  created_at: string
}

export interface ReferenceItem {
  type: 'entity' | 'file' | 'chapter' | 'skill'
  kind?: KbKind
  id?: string
  name: string
  path: string
  hint: string
  score?: number
}

export interface KnowledgeBaseSummary {
  kind: KbKind
  name: string
  count: number
  chunks: number
}

export interface KbConfig {
  top_k: number
  threshold: number
  mode: 'hybrid' | 'keyword' | 'vector'
  alpha: number
  chapter_limit: number | null
}

export interface ChunkItem {
  id: string
  kind: string
  ref: string
  title: string
  text: string
  chapter: number
  source: string
}

export type AppView =
  | 'chat'
  | 'experts'
  | 'skills'
  | 'knowledge'
  | 'memory'
  | 'approvals'
  | 'diagnostics'

export interface ModelSettings {
  base_url: string
  api_key: string
  model: string
  temperature: number
  context_window: number
}

export interface EmbeddingSettings {
  provider: 'none' | 'openai'
  base_url: string
  api_key: string
  model: string
  dimensions: number
}

export type RuleMode = 'allow' | 'ask' | 'deny'
export type SessionPermission = 'ask' | 'auto'

export interface PathRule {
  pattern: string
  read: RuleMode
  write: RuleMode
  delete: RuleMode
  note?: string
}

export interface CommandRule {
  pattern: string
  mode: RuleMode
  note: string
}

export interface NetworkSettings {
  default: 'allow' | 'deny'
  allow: string[]
}

export interface SandboxSettings {
  default_mode: SessionPermission
  rules: PathRule[]
  commands: CommandRule[]
  network: NetworkSettings
}

export interface LintIssue {
  rule: string
  severity: 'warn' | 'info'
  chapter: string
  message: string
  detail: string
}

export interface LintReport {
  issues: LintIssue[]
  stats: {
    chapters: number
    characters: number
    foreshadows: number
    warn: number
    info: number
  }
}

export interface McpServerSettings {
  name: string
  transport: 'stdio' | 'http'
  command: string
  args: string[]
  env: Record<string, string>
  url: string
  enabled: boolean
}

export interface McpServerStatus {
  name: string
  transport: string
  enabled: boolean
  connected: boolean
  tools: string[]
  error: string
}

export interface AppConfig {
  writer: ModelSettings
  extractor: ModelSettings
  embedding: EmbeddingSettings
  sandbox: SandboxSettings
  mcp: McpServerSettings[]
}

export type TimelineItem =
  | { id: string; type: 'user'; content: string; steering?: boolean; references?: ReferenceItem[] }
  | { id: string; type: 'assistant'; content: string; interrupted?: boolean }
  | {
      id: string
      type: 'tool'
      name: string
      input: string
      output?: string
      status: 'running' | 'done' | 'cancelled'
    }
  | { id: string; type: 'error'; content: string }
  | { id: string; type: 'turn_end'; meta: TurnMeta }

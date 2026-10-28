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
    steering?: boolean
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
  score: number
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

export interface ContextBundle {
  system_prompt: string
  items: ContextItem[]
  expert_id: string
  domain_id: string
  fingerprint: string
  total_chars: number
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
}

export interface ApprovalRequest {
  name: string
  args: Record<string, unknown>
  description: string
  target: string
  diff: string
  note: string
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

export type AppView = 'chat' | 'experts' | 'skills' | 'knowledge'

export interface ModelSettings {
  base_url: string
  api_key: string
  model: string
  temperature: number
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

export interface SandboxSettings {
  default_mode: SessionPermission
  rules: PathRule[]
}

export interface AppConfig {
  writer: ModelSettings
  extractor: ModelSettings
  embedding: EmbeddingSettings
  sandbox: SandboxSettings
}

export type TimelineItem =
  | { id: string; type: 'user'; content: string; steering?: boolean }
  | { id: string; type: 'assistant'; content: string }
  | {
      id: string
      type: 'tool'
      name: string
      input: string
      output?: string
      status: 'running' | 'done'
    }
  | { id: string; type: 'error'; content: string }
  | { id: string; type: 'turn_end'; meta: TurnMeta }

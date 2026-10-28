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
  created_at: string
  updated_at: string
}

export interface Message {
  id: number
  session_id: string
  role: 'user' | 'assistant'
  content: string
  meta?: { tool_calls?: { name: string; input: string }[] } | null
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

export interface AppConfig {
  writer: ModelSettings
  extractor: ModelSettings
  embedding: EmbeddingSettings
}

export type TimelineItem =
  | { id: string; type: 'user' | 'assistant'; content: string }
  | {
      id: string
      type: 'tool'
      name: string
      input: string
      output?: string
      status: 'running' | 'done'
    }
  | { id: string; type: 'error'; content: string }

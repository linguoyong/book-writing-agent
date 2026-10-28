import { useState } from 'react'
import { Plus, Trash2, X } from 'lucide-react'
import { useAppStore } from '../store'
import type {
  AppConfig,
  EmbeddingSettings,
  ModelSettings,
  PathRule,
  RuleMode,
  SessionPermission
} from '../types'

export default function SettingsModal(): React.JSX.Element | null {
  const config = useAppStore((state) => state.config)
  const saveConfig = useAppStore((state) => state.saveConfig)
  const setSettingsOpen = useAppStore((state) => state.setSettingsOpen)

  const [draft, setDraft] = useState<AppConfig | null>(config)

  if (!draft) return null

  const setWriter = (patch: Partial<ModelSettings>): void =>
    setDraft({ ...draft, writer: { ...draft.writer, ...patch } })
  const setExtractor = (patch: Partial<ModelSettings>): void =>
    setDraft({ ...draft, extractor: { ...draft.extractor, ...patch } })
  const setEmbedding = (patch: Partial<EmbeddingSettings>): void =>
    setDraft({ ...draft, embedding: { ...draft.embedding, ...patch } })

  const setRules = (rules: PathRule[]): void =>
    setDraft({ ...draft, sandbox: { ...draft.sandbox, rules } })
  const patchRule = (index: number, patch: Partial<PathRule>): void =>
    setRules(draft.sandbox.rules.map((rule, i) => (i === index ? { ...rule, ...patch } : rule)))
  const addRule = (): void =>
    setRules([
      ...draft.sandbox.rules,
      { pattern: 'secrets/**', read: 'ask', write: 'ask', delete: 'deny' }
    ])
  const removeRule = (index: number): void =>
    setRules(draft.sandbox.rules.filter((_, i) => i !== index))
  const setMode = (index: number, op: 'read' | 'write' | 'delete', mode: RuleMode): void =>
    patchRule(index, { [op]: mode } as Partial<PathRule>)

  return (
    <div className="modal-mask" onClick={() => setSettingsOpen(false)}>
      <div className="modal" style={{ width: 640 }} onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <span>模型设置</span>
          <button className="icon-btn" onClick={() => setSettingsOpen(false)}>
            <X size={14} />
          </button>
        </div>

        <div className="modal-body">
          <ModelSection
            title="写作模型"
            hint="用于对话、续写与设定审校"
            settings={draft.writer}
            onChange={setWriter}
            withCompaction
          />
          <ModelSection
            title="抽取模型"
            hint="用于导入时的逐章结构化抽取，建议选便宜且稳定的模型"
            settings={draft.extractor}
            onChange={setExtractor}
          />

          <div style={{ borderTop: '1px solid var(--border)', paddingTop: 12 }}>
            <div style={{ fontSize: 12.5, marginBottom: 8 }}>向量检索</div>
            <div className="field">
              <label>向量服务</label>
              <select
                value={draft.embedding.provider}
                onChange={(event) =>
                  setEmbedding({ provider: event.target.value as 'none' | 'openai' })
                }
              >
                <option value="none">关闭（仅全文检索）</option>
                <option value="openai">OpenAI 兼容 embedding 接口</option>
              </select>
            </div>
            {draft.embedding.provider !== 'none' && (
              <>
                <div className="field" style={{ marginTop: 8 }}>
                  <label>Embedding Base URL</label>
                  <input
                    value={draft.embedding.base_url}
                    onChange={(event) => setEmbedding({ base_url: event.target.value })}
                    placeholder="https://api.openai.com/v1"
                  />
                </div>
                <div className="field" style={{ marginTop: 8 }}>
                  <label>API Key</label>
                  <input
                    type="password"
                    value={draft.embedding.api_key}
                    onChange={(event) => setEmbedding({ api_key: event.target.value })}
                  />
                </div>
                <div className="field" style={{ marginTop: 8 }}>
                  <label>模型名</label>
                  <input
                    value={draft.embedding.model}
                    onChange={(event) => setEmbedding({ model: event.target.value })}
                    placeholder="bge-m3"
                  />
                </div>
              </>
            )}
          </div>

          <div style={{ borderTop: '1px solid var(--border)', marginTop: 14, paddingTop: 12 }}>
            <div style={{ fontSize: 12.5 }}>文件权限</div>
            <div style={{ fontSize: 11, color: 'var(--faint)', marginBottom: 8, lineHeight: 1.6 }}>
              工作区内路径，支持 glob（如 secrets/**、**/*.key）。allow 放行、ask 需审批、deny 直接拒绝；
              未命中规则的写入按会话的权限模式处理。
            </div>
            <div className="field" style={{ marginBottom: 10 }}>
              <label>新会话默认模式</label>
              <select
                value={draft.sandbox.default_mode}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    sandbox: {
                      ...draft.sandbox,
                      default_mode: event.target.value as SessionPermission
                    }
                  })
                }
              >
                <option value="ask">请求批准</option>
                <option value="auto">完全访问</option>
              </select>
            </div>
            <div className="rule-head">
              <span>路径</span>
              <span>读</span>
              <span>写</span>
              <span>删</span>
              <span />
            </div>
            {draft.sandbox.rules.map((rule, index) => (
              <div className="rule-row" key={`${rule.pattern}-${index}`}>
                <input
                  value={rule.pattern}
                  onChange={(event) => patchRule(index, { pattern: event.target.value })}
                  placeholder="secrets/**"
                  title={rule.note}
                />
                {(['read', 'write', 'delete'] as const).map((op) => (
                  <select
                    key={op}
                    value={rule[op]}
                    onChange={(event) =>
                      setMode(index, op, event.target.value as RuleMode)
                    }
                  >
                    <option value="allow">allow</option>
                    <option value="ask">ask</option>
                    <option value="deny">deny</option>
                  </select>
                ))}
                <button
                  className="icon-btn"
                  onClick={() => removeRule(index)}
                  title="删除规则"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
            <button className="small-btn" style={{ marginTop: 6 }} onClick={addRule}>
              <Plus size={12} />
              添加规则
            </button>
          </div>
        </div>

        <div className="modal-footer">
          <button className="ghost-btn" onClick={() => setSettingsOpen(false)}>
            取消
          </button>
          <button className="primary-btn" onClick={() => void saveConfig(draft)}>
            保存
          </button>
        </div>
      </div>
    </div>
  )
}

function ModelSection({
  title,
  hint,
  settings,
  onChange,
  withCompaction = false
}: {
  title: string
  hint: string
  settings: ModelSettings
  onChange: (patch: Partial<ModelSettings>) => void
  withCompaction?: boolean
}): React.JSX.Element {
  return (
    <div>
      <div style={{ fontSize: 12.5 }}>{title}</div>
      <div style={{ fontSize: 11, color: 'var(--faint)', marginBottom: 8 }}>{hint}</div>
      <div className="field">
        <label>Base URL</label>
        <input
          value={settings.base_url}
          onChange={(event) => onChange({ base_url: event.target.value })}
          placeholder="https://api.deepseek.com/v1"
        />
      </div>
      <div className="field" style={{ marginTop: 8 }}>
        <label>API Key</label>
        <input
          type="password"
          value={settings.api_key}
          onChange={(event) => onChange({ api_key: event.target.value })}
        />
      </div>
      <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
        <div className="field" style={{ flex: 2 }}>
          <label>模型名</label>
          <input
            value={settings.model}
            onChange={(event) => onChange({ model: event.target.value })}
            placeholder="deepseek-chat"
          />
        </div>
        <div className="field" style={{ flex: 1 }}>
          <label>Temperature</label>
          <input
            type="number"
            step="0.1"
            min="0"
            max="2"
            value={settings.temperature}
            onChange={(event) => onChange({ temperature: Number(event.target.value) })}
          />
        </div>
      </div>
      {withCompaction && (
        <div className="field" style={{ marginTop: 8 }}>
          <label>上下文长度</label>
          <select
            value={settings.context_window}
            onChange={(event) => onChange({ context_window: Number(event.target.value) })}
          >
            <option value={500000}>500K</option>
            <option value={1000000}>1M</option>
          </select>
          <div className="field-hint">
            当前默认 DeepSeek。到窗口 80% 时自动摘要压缩：旧消息交给摘要模型收成一段上下文，
            原文另存到 /conversation_history 可回读；最后 12 条始终保留原文。
          </div>
        </div>
      )}
    </div>
  )
}

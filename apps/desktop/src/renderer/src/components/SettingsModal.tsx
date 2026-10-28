import { useState } from 'react'
import { X } from 'lucide-react'
import { useAppStore } from '../store'
import type { AppConfig, EmbeddingSettings, ModelSettings } from '../types'

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

  return (
    <div className="modal-mask" onClick={() => setSettingsOpen(false)}>
      <div className="modal" style={{ width: 560 }} onClick={(event) => event.stopPropagation()}>
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
  onChange
}: {
  title: string
  hint: string
  settings: ModelSettings
  onChange: (patch: Partial<ModelSettings>) => void
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
    </div>
  )
}

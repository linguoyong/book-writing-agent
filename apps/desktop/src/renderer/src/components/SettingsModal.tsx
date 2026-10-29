import { useEffect, useState } from 'react'
import { Plus, RefreshCw, Trash2, X } from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'
import type {
  AppConfig,
  EmbeddingSettings,
  McpServerSettings,
  McpServerStatus,
  ModelProfile,
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
  const [mcpServers, setMcpServers] = useState<McpServerStatus[]>([])
  const [mcpBusy, setMcpBusy] = useState(false)

  const loadMcp = async (force = false): Promise<void> => {
    setMcpBusy(true)
    try {
      const result = force ? await api.mcpReload() : await api.mcpStatus()
      setMcpServers(result.servers)
    } catch {
      setMcpServers([])
    }
    setMcpBusy(false)
  }

  useEffect(() => {
    void loadMcp()
  }, [])

  if (!draft) return null

  const setExtractor = (patch: Partial<ModelSettings>): void =>
    setDraft({ ...draft, extractor: { ...draft.extractor, ...patch } })
  const setEmbedding = (patch: Partial<EmbeddingSettings>): void =>
    setDraft({ ...draft, embedding: { ...draft.embedding, ...patch } })

  const patchModel = (index: number, patch: Partial<ModelProfile>): void =>
    setDraft({
      ...draft,
      models: draft.models.map((item, i) => (i === index ? { ...item, ...patch } : item))
    })
  const addModel = (): void =>
    setDraft({
      ...draft,
      models: [
        ...draft.models,
        {
          id: `model-${Date.now().toString(36)}`,
          name: '新模型',
          base_url: '',
          api_key: '',
          model: '',
          context_window: 1_000_000,
          max_output_tokens: 64_000,
          temperature: 0.7
        }
      ]
    })
  const removeModel = (index: number): void => {
    if (draft.models.length <= 1) return
    const removed = draft.models[index]
    const models = draft.models.filter((_, i) => i !== index)
    setDraft({
      ...draft,
      models,
      active_model_id:
        draft.active_model_id === removed.id ? models[0].id : draft.active_model_id
    })
  }

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

  const setSandbox = (patch: Partial<AppConfig['sandbox']>): void =>
    setDraft({ ...draft, sandbox: { ...draft.sandbox, ...patch } })
  const addCommand = (): void =>
    setSandbox({
      commands: [...draft.sandbox.commands, { pattern: 'git status*', mode: 'allow', note: '' }]
    })
  const patchCommand = (index: number, patch: Partial<AppConfig['sandbox']['commands'][number]>): void =>
    setSandbox({
      commands: draft.sandbox.commands.map((rule, i) => (i === index ? { ...rule, ...patch } : rule))
    })
  const removeCommand = (index: number): void =>
    setSandbox({ commands: draft.sandbox.commands.filter((_, i) => i !== index) })

  const addServer = (): void =>
    setDraft({
      ...draft,
      mcp: [
        ...draft.mcp,
        { name: '', transport: 'stdio', command: '', args: [], env: {}, url: '', enabled: true }
      ]
    })
  const patchServer = (index: number, patch: Partial<McpServerSettings>): void =>
    setDraft({ ...draft, mcp: draft.mcp.map((srv, i) => (i === index ? { ...srv, ...patch } : srv)) })
  const removeServer = (index: number): void =>
    setDraft({ ...draft, mcp: draft.mcp.filter((_, i) => i !== index) })

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
          <div>
            <div style={{ fontSize: 12.5 }}>模型</div>
            <div style={{ fontSize: 11, color: 'var(--faint)', margin: '2px 0 8px', lineHeight: 1.6 }}>
              可添加任意 OpenAI 兼容来源。对话按会话选择模型，新会话用标「默认」的那个；
              上下文与输出长度用于装配/压缩预算，实际上限由服务端模型决定。
            </div>
            {draft.models.map((item, index) => (
              <div className="model-card" key={item.id}>
                <div className="model-card-head">
                  <input
                    className="model-card-name"
                    value={item.name}
                    placeholder="显示名称，例如 DeepSeek V4"
                    onChange={(event) => patchModel(index, { name: event.target.value })}
                  />
                  <label className="model-default">
                    <input
                      type="radio"
                      name="default-model"
                      checked={draft.active_model_id === item.id}
                      onChange={() => setDraft({ ...draft, active_model_id: item.id })}
                    />
                    默认
                  </label>
                  <button
                    className="icon-btn"
                    onClick={() => removeModel(index)}
                    disabled={draft.models.length <= 1}
                    title="删除模型"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
                <div className="model-grid">
                  <label className="model-field">
                    <span>Base URL</span>
                    <input
                      value={item.base_url}
                      placeholder="https://api.deepseek.com/v1"
                      onChange={(event) => patchModel(index, { base_url: event.target.value })}
                    />
                  </label>
                  <label className="model-field">
                    <span>模型名</span>
                    <input
                      value={item.model}
                      placeholder="deepseek-chat"
                      onChange={(event) => patchModel(index, { model: event.target.value })}
                    />
                  </label>
                  <label className="model-field wide">
                    <span>API Key</span>
                    <input
                      type="password"
                      value={item.api_key}
                      onChange={(event) => patchModel(index, { api_key: event.target.value })}
                    />
                  </label>
                  <label className="model-field">
                    <span>上下文（token）</span>
                    <input
                      type="number"
                      min={8000}
                      step={1000}
                      value={item.context_window}
                      onChange={(event) =>
                        patchModel(index, {
                          context_window: Number(event.target.value) || 1_000_000
                        })
                      }
                    />
                  </label>
                  <label className="model-field">
                    <span>输出（token）</span>
                    <input
                      type="number"
                      min={512}
                      step={512}
                      value={item.max_output_tokens}
                      onChange={(event) =>
                        patchModel(index, {
                          max_output_tokens: Number(event.target.value) || 64_000
                        })
                      }
                    />
                  </label>
                </div>
                {item.api_key === '***' && (
                  <div className="field-hint">
                    已配置（显示为 ***），不改动即保留；清空后保存则删除。
                  </div>
                )}
              </div>
            ))}
            <button className="small-btn" style={{ marginTop: 6 }} onClick={addModel}>
              <Plus size={12} />
              添加模型
            </button>
          </div>

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
                  {draft.embedding.api_key === '***' && (
                    <div className="field-hint">已配置（显示为 ***），不改动即保留；清空后保存则删除。</div>
                  )}
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

            <div style={{ borderTop: '1px solid var(--border)', marginTop: 14, paddingTop: 12 }}>
              <div style={{ fontSize: 12.5, marginBottom: 4 }}>命令白名单</div>
              <div className="field-hint" style={{ marginBottom: 8 }}>
                给将来的 shell 类工具做门禁：整条命令按 glob 匹配，先命中先生效；没命中任何规则一律拒绝。
              </div>
              <div className="rule-head">
                <span>命令</span>
                <span>动作</span>
                <span />
              </div>
              {draft.sandbox.commands.map((rule, index) => (
                <div className="rule-row rule-row-2" key={`${rule.pattern}-${index}`}>
                  <input
                    value={rule.pattern}
                    onChange={(event) => patchCommand(index, { pattern: event.target.value })}
                    placeholder="git status*"
                    title={rule.note}
                  />
                  <select
                    value={rule.mode}
                    onChange={(event) => patchCommand(index, { mode: event.target.value as RuleMode })}
                  >
                    <option value="allow">allow</option>
                    <option value="ask">ask</option>
                    <option value="deny">deny</option>
                  </select>
                  <button className="icon-btn" onClick={() => removeCommand(index)} title="删除规则">
                    <Trash2 size={12} />
                  </button>
                </div>
              ))}
              <button className="small-btn" style={{ marginTop: 6 }} onClick={addCommand}>
                <Plus size={12} />
                添加命令规则
              </button>

              <div style={{ fontSize: 12.5, marginTop: 14, marginBottom: 4 }}>网络</div>
              <div className="field-hint" style={{ marginBottom: 8 }}>
                给抓取类工具做门禁：默认拒绝，只有放行列表里的域名（含子域名）能出网。
              </div>
              <div className="field">
                <label>默认策略</label>
                <select
                  value={draft.sandbox.network.default}
                  onChange={(event) =>
                    setSandbox({
                      network: {
                        ...draft.sandbox.network,
                        default: event.target.value as 'allow' | 'deny'
                      }
                    })
                  }
                >
                  <option value="deny">拒绝（推荐）</option>
                  <option value="allow">允许</option>
                </select>
              </div>
              <div className="field" style={{ marginTop: 8 }}>
                <label>放行域名（每行一个，如 api.deepseek.com）</label>
                <textarea
                  className="domain-list"
                  value={draft.sandbox.network.allow.join('\n')}
                  spellCheck={false}
                  onChange={(event) =>
                    setSandbox({
                      network: {
                        ...draft.sandbox.network,
                        allow: event.target.value.split('\n').map((item) => item.trim()).filter(Boolean)
                      }
                    })
                  }
                />
              </div>
            </div>
          </div>

            <div style={{ borderTop: '1px solid var(--border)', marginTop: 14, paddingTop: 12 }}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  marginBottom: 4
                }}
              >
                <div style={{ fontSize: 12.5 }}>MCP 连接器</div>
                <button
                  className="ghost-btn"
                  style={{ height: 24, padding: '0 8px', fontSize: 11 }}
                  disabled={mcpBusy}
                  onClick={() => void loadMcp(true)}
                  title="重连所有服务器并刷新工具列表"
                >
                  <RefreshCw size={11} /> 重连
                </button>
              </div>
              <div className="field-hint" style={{ marginBottom: 8 }}>
                stdio：本地命令（如 python xxx.py）；http：streamable http 端点。工具会以
                服务器名为前缀注入对话；MCP 工具不经过路径沙箱与 diff 审批，只开自己信得过的服务。
              </div>
              {draft.mcp.map((server, index) => (
                <div className="mcp-server" key={`${server.name}-${index}`}>
                  <label className="mcp-enabled" title="启用后注入对话">
                    <input
                      type="checkbox"
                      checked={server.enabled}
                      onChange={(event) => patchServer(index, { enabled: event.target.checked })}
                    />
                  </label>
                  <input
                    className="mcp-name"
                    value={server.name}
                    placeholder="名称"
                    onChange={(event) => patchServer(index, { name: event.target.value })}
                  />
                  <select
                    value={server.transport}
                    onChange={(event) =>
                      patchServer(index, { transport: event.target.value as 'stdio' | 'http' })
                    }
                  >
                    <option value="stdio">stdio</option>
                    <option value="http">http</option>
                  </select>
                  {server.transport === 'stdio' ? (
                    <>
                      <input
                        value={server.command}
                        placeholder="命令，如 D:/xxx/python.exe"
                        onChange={(event) => patchServer(index, { command: event.target.value })}
                      />
                      <input
                        value={server.args.join(' ')}
                        placeholder="参数（空格分隔）"
                        onChange={(event) =>
                          patchServer(index, {
                            args: event.target.value.split(' ').map((item) => item.trim()).filter(Boolean)
                          })
                        }
                      />
                    </>
                  ) : (
                    <input
                      value={server.url}
                      placeholder="http(s):// endpoint"
                      onChange={(event) => patchServer(index, { url: event.target.value })}
                    />
                  )}
                  <button className="icon-btn" onClick={() => removeServer(index)} title="删除">
                    <Trash2 size={12} />
                  </button>
                </div>
              ))}
              <button className="small-btn" style={{ marginTop: 6 }} onClick={addServer}>
                <Plus size={12} />
                添加服务器
              </button>
              {mcpServers.length > 0 && (
                <div className="mcp-status">
                  {mcpServers.map((server) => (
                    <div className="mcp-status-row" key={server.name}>
                      <span className={`mcp-dot ${server.connected ? 'on' : 'off'}`} />
                      <span className="mcp-status-name">{server.name}</span>
                      <span className="mcp-status-info">
                        {server.connected
                          ? `已连接 · ${(server.tools || []).join('、') || '无工具'}`
                          : server.error || '未连接'}
                      </span>
                    </div>
                  ))}
                </div>
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
        {settings.api_key === '***' && (
          <div className="field-hint">已配置（显示为 ***），不改动即保留；清空后保存则删除。</div>
        )}
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

import { useMemo, useState } from 'react'
import { BookOpenCheck, Loader2, MessageSquarePlus, Search, Sparkles } from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'

export default function ExpertsPage(): React.JSX.Element {
  const experts = useAppStore((state) => state.experts)
  const currentExpertId = useAppStore((state) => state.currentExpertId)
  const setExpert = useAppStore((state) => state.setExpert)
  const setView = useAppStore((state) => state.setView)
  const startBuilder = useAppStore((state) => state.startBuilder)
  const project = useAppStore((state) => state.activeProject)
  const loadExperts = useAppStore((state) => state.loadExperts)
  const showToast = useAppStore((state) => state.showToast)

  const [query, setQuery] = useState('')
  const [importing, setImporting] = useState(false)

  const importFromWork = async (): Promise<void> => {
    if (!project || importing) return
    const path = await window.desktop?.pickTextFile?.()
    if (!path) return
    setImporting(true)
    showToast('正在提炼风格，通常需要 10–40 秒…')
    try {
      const result = await api.importStyle(project.id, path)
      await loadExperts()
      const skillNote = result.skill ? `，技能「${result.skill.name}」` : ''
      showToast(`已生成专家「${result.expert.name}」${skillNote}`)
    } catch (error) {
      showToast((error as Error).message || '导入失败')
    } finally {
      setImporting(false)
    }
  }

  const filtered = useMemo(() => {
    const keyword = query.trim()
    if (!keyword) return experts
    return experts.filter(
      (expert) =>
        expert.name.includes(keyword) ||
        expert.description.includes(keyword) ||
        expert.tags.some((tag) => tag.includes(keyword))
    )
  }, [experts, query])

  return (
    <div className="page">
      <div className="page-header">
        <div className="page-title-block">
          <h1>专家</h1>
          <p>为不同写作任务准备的人设、方法与工作流程</p>
        </div>
        <div className="page-actions">
          <div className="search-box">
            <Search size={14} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索专家"
            />
          </div>
          <button
            className="primary-btn"
            onClick={() => void importFromWork()}
            disabled={importing || !project}
            title={project ? '从 txt/md 作品提炼风格专家与写作技能' : '先打开一个空间'}
          >
            {importing ? <Loader2 size={14} className="spin" /> : <BookOpenCheck size={14} />}
            {importing ? '提炼中…' : '从作品导入'}
          </button>
          <button className="primary-btn" onClick={() => void startBuilder('expert')}>
            <MessageSquarePlus size={14} />
            对话创建
          </button>
        </div>
      </div>

      <div className="page-scroll">
        <div className="expert-page-grid">
          {filtered.map((expert) => {
            const active = expert.id === currentExpertId
            return (
              <div key={expert.id} className={`expert-card-page ${active ? 'active' : ''}`}>
                <div className="expert-avatar">{expert.avatar || '专'}</div>
                <div className="expert-card-main">
                  <div className="expert-card-title">
                    <span>{expert.name}</span>
                    {active && <span className="badge-active">当前</span>}
                  </div>
                  <div className="expert-card-desc">{expert.description}</div>
                  <div className="tag-row">
                    {(expert.tags || []).map((tag) => (
                      <span key={tag} className="tag">
                        {tag}
                      </span>
                    ))}
                    {expert.skills.length > 0 && (
                      <span className="tag tag-skill">技能 ×{expert.skills.length}</span>
                    )}
                  </div>
                </div>
                <div className="expert-card-actions">
                  <button
                    className="small-btn"
                    onClick={() => {
                      setExpert(expert.id)
                      setView('chat')
                    }}
                  >
                    {active ? '去对话' : '设为当前'}
                  </button>
                </div>
              </div>
            )
          })}

          {filtered.length === 0 && (
            <div className="panel-empty">
              <Sparkles size={18} />
              <div>还没有匹配的专家</div>
              <div style={{ fontSize: 12 }}>点击右上角「对话创建」，让 Agent 帮你写一个</div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

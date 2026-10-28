import { useEffect, useMemo, useState } from 'react'
import { MessageSquarePlus, RefreshCw, Search, Wand2 } from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'
import type { Skill } from '../types'

export default function SkillsPage(): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const startBuilder = useAppStore((state) => state.startBuilder)

  const [skills, setSkills] = useState<Skill[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)

  const load = async (): Promise<void> => {
    if (!project) {
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      setSkills(await api.skills(project.id))
    } catch {
      setSkills([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [project?.id])

  const filtered = useMemo(() => {
    const keyword = query.trim()
    if (!keyword) return skills
    return skills.filter(
      (skill) => skill.name.includes(keyword) || skill.description.includes(keyword)
    )
  }, [skills, query])

  return (
    <div className="page">
      <div className="page-header">
        <div className="page-title-block">
          <h1>技能</h1>
          <p>可复用的写作流程与检查清单，放在项目的 skills/ 目录下</p>
        </div>
        <div className="page-actions">
          <div className="search-box">
            <Search size={14} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索技能"
            />
          </div>
          <button className="ghost-btn" onClick={() => void load()}>
            <RefreshCw size={13} />
            刷新
          </button>
          <button className="primary-btn" onClick={() => void startBuilder('skill')}>
            <MessageSquarePlus size={14} />
            对话创建
          </button>
        </div>
      </div>

      <div className="page-scroll">
        {loading && <div className="panel-empty">正在读取技能…</div>}

        {!loading && filtered.length === 0 && (
          <div className="empty-block">
            <Wand2 size={20} />
            <div>还没有技能</div>
            <p>
              技能是写在 <code>skills/&lt;技能名&gt;/SKILL.md</code> 里的可复用流程。
              点「对话创建」描述你想固化的写作方法，Agent 会帮你写出这个文件。
            </p>
          </div>
        )}

        <div className="skill-page-grid">
          {filtered.map((skill) => (
            <div key={skill.path} className="skill-card-page">
              <div className="skill-card-head">
                <div className="skill-icon">
                  <Wand2 size={15} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="expert-card-title">
                    <span>{skill.name}</span>
                    <span className={`skill-state ${skill.enabled ? 'on' : 'off'}`}>
                      {skill.enabled ? '启用' : '停用'}
                    </span>
                  </div>
                  <div className="expert-card-desc">{skill.description || '暂无说明'}</div>
                </div>
              </div>
              <div className="skill-path">{skill.path}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

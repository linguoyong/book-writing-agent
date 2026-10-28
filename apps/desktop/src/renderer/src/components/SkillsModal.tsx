import { useEffect, useState } from 'react'
import { RefreshCw, Wand2, X } from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'
import type { Skill } from '../types'

export default function SkillsModal(): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const setSkillsModalOpen = useAppStore((state) => state.setSkillsModalOpen)

  const [skills, setSkills] = useState<Skill[]>([])
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

  return (
    <div className="modal-mask" onClick={() => setSkillsModalOpen(false)}>
      <div className="modal" style={{ width: 520 }} onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Wand2 size={14} />
            技能管理
          </span>
          <button className="icon-btn" onClick={() => setSkillsModalOpen(false)}>
            <X size={14} />
          </button>
        </div>

        <div className="modal-body">
          {loading && <div className="panel-empty">正在读取技能…</div>}

          {!loading && skills.length === 0 && (
            <div className="panel-empty" style={{ textAlign: 'left', padding: '10px 4px' }}>
              还没有技能。
              <br />
              在书稿项目的 <code>skills/&lt;技能名&gt;/SKILL.md</code> 中编写技能，
              支持 front-matter 字段 name、description、enabled。
              <br />
              示例：<code>skills/foreshadow/SKILL.md</code> 定义伏笔检查流程。
            </div>
          )}

          {!loading &&
            skills.map((skill) => (
              <div key={skill.path} className="skill-card">
                <div className="expert-card-head">
                  <span>{skill.name}</span>
                  <span style={{ fontSize: 10.5, color: skill.enabled ? 'var(--green)' : 'var(--faint)' }}>
                    {skill.enabled ? '启用' : '停用'}
                  </span>
                </div>
                <div className="expert-card-desc">{skill.description}</div>
                <div className="skill-path">{skill.path}</div>
              </div>
            ))}

          <div style={{ fontSize: 11, color: 'var(--faint)', lineHeight: 1.7 }}>
            目前技能只做目录扫描展示，渐进加载与 @ 调用将在 P1 实现。
          </div>
        </div>

        <div className="modal-footer">
          <button className="ghost-btn" onClick={() => void load()}>
            <RefreshCw size={12} style={{ marginRight: 4 }} />
            刷新
          </button>
          <button className="ghost-btn" onClick={() => setSkillsModalOpen(false)}>
            关闭
          </button>
        </div>
      </div>
    </div>
  )
}

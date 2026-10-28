import { Check, Sparkles, X } from 'lucide-react'
import { EXPERTS } from '../experts'
import { useAppStore } from '../store'

export default function ExpertModal(): React.JSX.Element {
  const currentExpertId = useAppStore((state) => state.currentExpertId)
  const setExpert = useAppStore((state) => state.setExpert)
  const setExpertModalOpen = useAppStore((state) => state.setExpertModalOpen)

  return (
    <div className="modal-mask" onClick={() => setExpertModalOpen(false)}>
      <div className="modal" style={{ width: 520 }} onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Sparkles size={14} />
            专家 · 写作风格
          </span>
          <button className="icon-btn" onClick={() => setExpertModalOpen(false)}>
            <X size={14} />
          </button>
        </div>

        <div className="modal-body">
          <div style={{ fontSize: 11.5, color: 'var(--faint)', lineHeight: 1.7 }}>
            专家会被注入写作模型，切换后影响后续对话与续写。输入框底部会显示当前专家。
          </div>
          <div className="expert-list">
            {EXPERTS.map((expert) => {
              const active = expert.id === currentExpertId
              return (
                <button
                  key={expert.id}
                  className={`expert-card ${active ? 'active' : ''}`}
                  onClick={() => {
                    setExpert(expert.id)
                    setExpertModalOpen(false)
                  }}
                >
                  <div className="expert-card-head">
                    <span>{expert.name}</span>
                    {active && <Check size={13} />}
                  </div>
                  <div className="expert-card-desc">{expert.description}</div>
                </button>
              )
            })}
          </div>
        </div>

        <div className="modal-footer">
          <button className="ghost-btn" onClick={() => setExpertModalOpen(false)}>
            关闭
          </button>
        </div>
      </div>
    </div>
  )
}

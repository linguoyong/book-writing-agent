import { useEffect, useState } from 'react'
import { FolderOpen, Loader2, X } from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'
import type { DeconstructStatus } from '../types'

export default function DeconstructModal({ onClose }: { onClose: () => void }): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const showToast = useAppStore((state) => state.showToast)
  const refreshOverview = useAppStore((state) => state.refreshOverview)
  const [source, setSource] = useState('')
  const [groups, setGroups] = useState(3)
  const [expert, setExpert] = useState(true)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<DeconstructStatus | null>(null)

  const pick = async (): Promise<void> => {
    const path = await window.desktop?.pickTextFile?.()
    if (path) {
      setSource(path)
      setStatus(null)
    }
  }

  const start = async (): Promise<void> => {
    if (!project || busy) return
    setBusy(true)
    setStatus({ status: 'running', progress: {} })
    try {
      await api.deconstructStart(project.id, {
        source: source.trim(),
        group_size: 3,
        max_groups: Math.max(0, Math.floor(groups)),
        create_expert: expert
      })
    } catch (error) {
      setBusy(false)
      setStatus(null)
      showToast((error as Error).message)
    }
  }

  const stop = async (): Promise<void> => {
    if (!project) return
    await api.deconstructStop(project.id).catch(() => undefined)
    showToast('已请求停止，当前这一组跑完就会停下')
  }

  useEffect(() => {
    if (!busy || !project) return
    let alive = true
    const timer = window.setInterval(() => {
      void api
        .deconstructStatus(project.id)
        .then((data) => {
          if (!alive) return
          setStatus(data)
          if (data.status === 'done' || data.status === 'stopped' || data.status === 'error') {
            setBusy(false)
            if (data.status === 'done' || data.status === 'stopped') {
              const result = data.result ?? {}
              showToast(
                `${data.status === 'stopped' ? '拆解已停止' : '拆解完成'}：${result.groups ?? 0} 组 / ${result.chapters ?? 0} 章，新增实体 ${result.entities ?? 0} 个`
              )
              void refreshOverview?.()
            } else if (data.error) {
              showToast(`拆解失败：${data.error}`)
            }
          }
        })
        .catch(() => undefined)
    }, 1500)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [busy, project, showToast, refreshOverview])

  const progress = status?.progress ?? {}
  const done = status?.status === 'done'

  return (
    <div className="modal-mask" onClick={busy ? undefined : onClose}>
      <div className="modal dc-modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <div>
            拆解一本作品
            <span className="rv-count">结构骨架 · 爽点节奏 · 设定实体</span>
          </div>
          <button className="icon-btn" onClick={onClose} disabled={busy} title="关闭">
            <X size={14} />
          </button>
        </div>

        <div className="modal-body dc-body">
          <p className="dc-hint">
            拆解会把作品里的角色、势力、地点、物品写进知识库，把可迁移的写法写成素材卡；
            勾选「生成专家」还会额外产出一个拆解专家和一个技能。建议先拆 3 组看效果。
          </p>

          <label className="dc-label">源文件</label>
          <div className="dc-file">
            <input
              value={source}
              placeholder="留空则使用已导入的 chapters/ 第一篇"
              onChange={(event) => setSource(event.target.value)}
              disabled={busy}
            />
            <button className="small-btn" onClick={() => void pick()} disabled={busy}>
              <FolderOpen size={12} /> 选择
            </button>
          </div>

          <div className="dc-row">
            <div>
              <label className="dc-label">拆几组（每组 3 章）</label>
              <input
                type="number"
                min={1}
                max={200}
                value={groups}
                onChange={(event) => setGroups(Number(event.target.value))}
                disabled={busy}
              />
            </div>
            <label className="dc-check">
              <input
                type="checkbox"
                checked={expert}
                onChange={(event) => setExpert(event.target.checked)}
                disabled={busy}
              />
              生成拆解专家与技能
            </label>
          </div>

          {status && (
            <div className="dc-progress">
              <div className="dc-progress-head">
                {busy && <Loader2 size={12} className="spin" />}
                {status.status === 'running' && '拆解中…'}
                {status.status === 'done' && '拆解完成'}
                {status.status === 'stopped' && '拆解已停止，已完成的结果已保留'}
                {status.status === 'error' && `拆解失败：${status.error ?? ''}`}
              </div>
              <div className="dc-progress-line">
                已处理 {progress.groups ?? 0} 组 · {progress.chapters ?? 0} 章 · 实体{' '}
                {progress.entities ?? 0} · 技法 {progress.techniques ?? 0}
                {progress.failed ? ` · 失败 ${progress.failed}` : ''}
              </div>
              {done && (
                <div className="dc-progress-line">
                  结果已写入知识库与素材卡；专家可在「专家」页选中使用。
                </div>
              )}
            </div>
          )}
        </div>

        <div className="modal-footer">
          {busy ? (
            <button className="small-btn" onClick={() => void stop()}>
              停止
            </button>
          ) : (
            <button className="small-btn" onClick={onClose}>
              关闭
            </button>
          )}
          <button className="primary-btn" onClick={() => void start()} disabled={busy}>
            {busy ? '拆解中…' : '开始拆解'}
          </button>
        </div>
      </div>
    </div>
  )
}

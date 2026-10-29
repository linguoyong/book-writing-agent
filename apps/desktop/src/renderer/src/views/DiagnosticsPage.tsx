import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, Stethoscope } from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'

interface LintIssue {
  rule: string
  severity: 'warn' | 'info'
  chapter: string
  message: string
  detail: string
}

interface LintReport {
  issues: LintIssue[]
  stats: {
    chapters: number
    characters: number
    foreshadows: number
    warn: number
    info: number
  }
}

const RULE_LABEL: Record<string, string> = {
  alias_mix: '别称混用',
  foreshadow_open: '未回收伏笔',
  timeline_back: '时间线倒退',
  unknown_speaker: '疑似漏登记'
}

export default function DiagnosticsPage(): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const [report, setReport] = useState<LintReport | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async (): Promise<void> => {
    if (!project) return
    setBusy(true)
    setError('')
    try {
      setReport(await api.lint(project.id))
    } catch (exc) {
      setError((exc as Error).message)
    }
    setBusy(false)
  }, [project])

  useEffect(() => {
    void load()
  }, [load])

  const stats = report?.stats

  return (
    <div className="page diagnostics-page">
      <div className="page-header">
        <div className="page-title-block">
          <h1>一致性诊断</h1>
          <p>规则体检：别称混用、未回收伏笔、时间线倒退、疑似漏登记的角色。</p>
        </div>
        <div className="page-actions">
          <button className="ghost-btn" onClick={() => void load()} disabled={busy}>
            <RefreshCw size={12} /> 重新体检
          </button>
        </div>
      </div>

      <div className="diag-stats">
        <div className="diag-stat">
          <span className="diag-num">{stats?.chapters ?? '—'}</span>
          <span className="diag-label">章节</span>
        </div>
        <div className="diag-stat">
          <span className="diag-num">{stats?.characters ?? '—'}</span>
          <span className="diag-label">角色</span>
        </div>
        <div className="diag-stat">
          <span className="diag-num">{stats?.foreshadows ?? '—'}</span>
          <span className="diag-label">未回收伏笔</span>
        </div>
        <div className="diag-stat warn">
          <span className="diag-num">{stats?.warn ?? '—'}</span>
          <span className="diag-label">警告</span>
        </div>
        <div className="diag-stat">
          <span className="diag-num">{stats?.info ?? '—'}</span>
          <span className="diag-label">提示</span>
        </div>
      </div>

      <div className="page-scroll">
        {error && <div className="panel-empty">体检失败：{error}</div>}
        {!error && report && report.issues.length === 0 && (
          <div className="panel-empty">
            <Stethoscope size={18} />
            <div style={{ marginTop: 6 }}>没有发现问题。写完新章节后回来再跑一次。</div>
          </div>
        )}
        {report?.issues.map((issue, index) => (
          <details className="diag-issue" key={`${issue.rule}-${index}`}>
            <summary>
              <span className={`diag-sev ${issue.severity}`}>
                {issue.severity === 'warn' ? '警告' : '提示'}
              </span>
              <span className="diag-rule">{RULE_LABEL[issue.rule] ?? issue.rule}</span>
              <span className="diag-msg">{issue.message}</span>
            </summary>
            <div className="diag-body">
              {issue.chapter && <div className="diag-chapter">位置：{issue.chapter}</div>}
              <div className="diag-detail">{issue.detail}</div>
            </div>
          </details>
        ))}
      </div>
    </div>
  )
}

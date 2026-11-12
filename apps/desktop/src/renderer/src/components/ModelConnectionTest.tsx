import { useEffect, useRef, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api } from '../api'
import type { ModelProbe, ModelTestRequest } from '../types'

export default function ModelConnectionTest({
  label,
  request
}: {
  label: string
  request: ModelTestRequest
}): React.JSX.Element {
  const fingerprint = JSON.stringify(request)
  const active = useRef<AbortController | null>(null)
  const [probing, setProbing] = useState(false)
  const [result, setResult] = useState<{ fingerprint: string; probe: ModelProbe } | null>(null)

  useEffect(() => {
    active.current?.abort()
    active.current = null
    setProbing(false)
    setResult(null)
    return () => active.current?.abort()
  }, [fingerprint])

  const test = async (): Promise<void> => {
    if (active.current && !active.current.signal.aborted) return
    const controller = new AbortController()
    active.current = controller
    setProbing(true)
    setResult(null)
    try {
      const probe = await api.testModel(request, controller.signal)
      if (!controller.signal.aborted) setResult({ fingerprint, probe })
    } catch (error) {
      if (!controller.signal.aborted) {
        setResult({
          fingerprint,
          probe: { ok: false, error: (error as Error).message || '测试失败，请稍后重试。', model: '', ms: 0 }
        })
      }
    } finally {
      if (!controller.signal.aborted) {
        active.current = null
        setProbing(false)
      }
    }
  }

  const probe = result?.fingerprint === fingerprint ? result.probe : null
  return (
    <div style={{ marginTop: 8 }}>
      <button
        className="small-btn"
        aria-label={`${label}测试连接`}
        disabled={probing}
        onClick={() => void test()}
      >
        <RefreshCw size={12} />
        {probing ? '测试中…' : '测试连接'}
      </button>
      <div className="field-hint" style={{ marginTop: 4 }}>
        测试当前填写的配置，无需先保存；会发送一条简短消息。
      </div>
      {probe && (
        <div
          role={probe.ok ? 'status' : 'alert'}
          style={{ marginTop: 5, fontSize: 11, color: probe.ok ? 'var(--green)' : 'var(--red)', overflowWrap: 'anywhere' }}
        >
          {probe.ok ? `连接成功 · ${probe.model} · ${probe.ms} ms` : probe.error}
        </div>
      )}
    </div>
  )
}

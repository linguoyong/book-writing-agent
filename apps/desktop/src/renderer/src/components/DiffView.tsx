import { useMemo, useState } from 'react'
import { parseDiff, splitSegments, type DiffHunk, type DiffLine, type FileBlock } from './diffcore'

function LineContent({ line }: { line: DiffLine }): React.JSX.Element {
  if (line.wordStart === undefined) {
    return <>{line.content || ' '}</>
  }
  return (
    <>
      {line.content.slice(0, line.wordStart)}
      <mark className={`diffv-word ${line.type}`}>
        {line.content.slice(line.wordStart, line.wordEnd)}
      </mark>
      {line.content.slice(line.wordEnd)}
    </>
  )
}

function HunkView({ hunk, prefix }: { hunk: DiffHunk; prefix: string }): React.JSX.Element {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const segments = useMemo(() => splitSegments(hunk, prefix), [hunk, prefix])

  const toggle = (key: string): void => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  return (
    <>
      {segments.map((segment) =>
        segment.kind === 'fold' && !expanded.has(segment.key) ? (
          <button
            key={segment.key}
            className="diffv-fold"
            onClick={() => toggle(segment.key)}
            title="点击展开未修改的行"
          >
            {segment.count} unmodified lines
          </button>
        ) : (
          <div key={segment.key} className="diffv-seg">
            {segment.lines.map((line, idx) => (
              <div key={`${segment.key}-${idx}`} className={`diffv-line ${line.type}`}>
                <span className="diffv-no">{line.oldNo ?? ''}</span>
                <span className="diffv-no">{line.newNo ?? ''}</span>
                <span className="diffv-code">
                  <LineContent line={line} />
                </span>
              </div>
            ))}
          </div>
        )
      )}
    </>
  )
}

export default function DiffView({
  text,
  showFileHeader = true
}: {
  text: string
  showFileHeader?: boolean
}): React.JSX.Element | null {
  const blocks = useMemo(() => parseDiff(text), [text])
  if (blocks.length === 0) return null
  return (
    <div className="diffv">
      {blocks.map((block, fileIdx) => (
        <div key={`${block.path}-${fileIdx}`} className="diffv-file">
          {showFileHeader && blocks.length > 1 && (
            <div className="diffv-file-head">
              <span className="diffv-path">{block.path}</span>
              <span className="diffv-stat">
                <b>+{block.additions}</b>
                <i>-{block.deletions}</i>
              </span>
            </div>
          )}
          {block.hunks.map((hunk, hunkIdx) => (
            <HunkView key={`${fileIdx}-${hunkIdx}`} hunk={hunk} prefix={`${fileIdx}-${hunkIdx}`} />
          ))}
        </div>
      ))}
    </div>
  )
}

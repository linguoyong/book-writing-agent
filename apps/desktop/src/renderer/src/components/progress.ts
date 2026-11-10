import type { TimelineItem } from '../types'

type ToolStep = Extract<TimelineItem, { type: 'tool' }>

const KINDS: Record<string, string> = {
  characters: '角色设定', factions: '势力设定', items: '物品设定', locations: '地点设定',
  world: '世界观', outline: '大纲', materials: '素材', styles: '文风资料'
}

function argsOf(step: ToolStep): Record<string, unknown> {
  try {
    const value: unknown = JSON.parse(step.input)
    return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
  } catch {
    return {}
  }
}

function targetOf(args: Record<string, unknown>): string {
  if (typeof args.meta_json === 'string') {
    try {
      const meta = JSON.parse(args.meta_json)
      if (typeof meta?.name === 'string') return meta.name.slice(0, 36)
    } catch { /* 截断的工具参数仍可回退到路径或 ID */ }
  }
  const value = args.file_path ?? args.path ?? args.chapter ?? args.entity_id ?? ''
  if (typeof value !== 'string' && typeof value !== 'number') return ''
  const name = String(value).replaceAll('\\', '/').split('/').filter(Boolean).pop() ?? ''
  return name.length > 36 ? `${name.slice(0, 35)}…` : name
}

const ACTIONS: Record<string, [string, string]> = {
  read_file: ['正在阅读文件', '已阅读文件'],
  ls: ['正在查看项目文件', '已查看项目文件'],
  glob: ['正在查找相关文件', '已查找相关文件'],
  grep: ['正在检索相关内容', '已检索相关内容'],
  kb_search: ['正在检索设定与原文', '已检索设定与原文'],
  kb_list: ['正在查看知识库', '已查看知识库'],
  kb_get: ['正在阅读设定', '已阅读设定'],
  kb_write: ['正在保存设定', '已保存设定'],
  write_file: ['正在保存文件', '已保存文件'],
  edit_file: ['正在修改文件', '已修改文件'],
  delete: ['正在删除文件', '已删除文件'],
  manuscript_read: ['正在阅读正文', '已阅读正文'],
  manuscript_write: ['正在保存正文', '已保存正文'],
  project_overview: ['正在了解书稿现状', '已了解书稿现状'],
  chapter_list: ['正在查看章节目录', '已查看章节目录'],
  chapter_read: ['正在阅读章节', '已阅读章节'],
  chapter_review: ['正在审阅章节', '已完成章节审阅'],
  deconstruct_source: ['正在拆解作品结构', '已完成作品拆解'],
  lint_consistency: ['正在检查设定一致性', '已检查设定一致性'],
  task: ['正在处理专项任务', '专项任务已返回结果'],
  memory_read: ['正在查看写作记忆', '已查看写作记忆'],
  memory_write: ['正在保存写作记忆', '已保存写作记忆']
}

export function toolProgress(step: ToolStep): string {
  if (step.status === 'cancelled') return '本次操作已停止'
  const done = step.status === 'done'
  if (done && /^(?:\s*\{\s*"error"\s*:|\s*(?:error:|permission denied|写入失败|编辑失败|删除失败|拆解失败|路径规则禁止|拒绝访问))/i.test(step.output ?? '')) {
    return '操作返回了提示，正在调整后续步骤'
  }
  const args = argsOf(step)
  const kind = typeof args.kind === 'string' ? KINDS[args.kind] : ''
  const label = step.name === 'kb_write' && kind
    ? `${done ? '已保存' : '正在保存'}${kind}`
    : (ACTIONS[step.name]?.[done ? 1 : 0] ?? (done ? '操作已返回结果' : '正在处理相关资料'))
  const target = targetOf(args)
  return target ? `${label} · ${target}` : label
}

export function executionProgress(items: TimelineItem[], answering: boolean): { current: string; recent: string } {
  const steps = items.filter((item): item is ToolStep => item.type === 'tool')
  const running = steps.filter((item) => item.status === 'running')
  const completed = steps.filter((item) => item.status === 'done')
  const latest = running[running.length - 1]
  const lastDone = completed[completed.length - 1]
  return {
    current: items.at(-1)?.type === 'notice' ? (items.at(-1) as { content: string }).content
      : latest ? toolProgress(latest) : answering ? '正在组织回复' : '正在整理已有资料，准备下一步',
    recent: lastDone ? `${toolProgress(lastDone)}${completed.length > 1 ? ` · 已完成 ${completed.length} 步` : ''}` : ''
  }
}

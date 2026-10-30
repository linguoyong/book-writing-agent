const { parseDiff } = require('./.workbuddy-diffview-test.js')

const ctx = Array.from({ length: 15 }, (_, i) => ' 上下文' + i).map((s) => ' ' + s)
const modified = [
  'diff --git a/manuscript/ch-001.md b/manuscript/ch-001.md',
  '--- a/manuscript/ch-001.md',
  '+++ b/manuscript/ch-001.md',
  '@@ -10,25 +10,27 @@',
  ...ctx,
  '-import { A, B, C } from old',
  '+import { A, B, C, D } from old',
  ...ctx,
  '+新加的一行',
  ' 上下文尾'
].join('\n')
const added = [
  'diff --git a/kb/new.md b/kb/new.md',
  'new file mode 100644',
  '--- /dev/null',
  '+++ b/kb/new.md',
  '@@ -0,0 +1,3 @@',
  '+第一行',
  '+第二行',
  '+第三行'
].join('\n')

const blocks = parseDiff(modified + '\n' + added)
const [m, a] = blocks
const hunk = m.hunks[0]
const ctxLines = hunk.lines.filter((l) => l.type === 'ctx')
const delLines = hunk.lines.filter((l) => l.type === 'del')
const addLines = hunk.lines.filter((l) => l.type === 'add')
console.log('blocks:', blocks.length, '| ctx:', ctxLines.length, 'del:', delLines.length, 'add:', addLines.length)
console.log(
  '行号 ctx[0]:',
  ctxLines[0].oldNo,
  ctxLines[0].newNo,
  '| del:',
  delLines[0].oldNo,
  delLines[0].newNo,
  '| add:',
  addLines[0].oldNo,
  addLines[0].newNo
)
console.log(
  '词级 del:',
  JSON.stringify(delLines[0].content.slice(delLines[0].wordStart, delLines[0].wordEnd)),
  '| add:',
  JSON.stringify(addLines[0].content.slice(addLines[0].wordStart, addLines[0].wordEnd))
)
console.log('新文件行号:', a.hunks[0].lines.map((l) => l.newNo).join())

if (ctxLines.length !== 15 || delLines.length !== 1 || addLines.length !== 2) {
  console.error('FAIL parse')
  process.exit(1)
}
if (delLines[0].wordStart === undefined || addLines[0].wordStart === undefined) {
  console.error('FAIL word')
  process.exit(1)
}
if (a.hunks[0].lines.map((l) => l.newNo).join() !== '1,2,3') {
  console.error('FAIL newfile')
  process.exit(1)
}
console.log('OK')

export interface Expert {
  id: string
  name: string
  description: string
  prompt: string
}

export const EXPERTS: Expert[] = [
  {
    id: 'general',
    name: '通用',
    description: '不额外约束风格，按你的描述写',
    prompt: ''
  },
  {
    id: 'cold',
    name: '冷峻克制',
    description: '短句为主，少形容词，情绪藏在动作里',
    prompt: '冷峻克制的第三人称叙事，短句为主，少用形容词，情绪藏在动作里'
  },
  {
    id: 'lyrical',
    name: '细腻抒情',
    description: '注重感官与心理描写，节奏舒缓',
    prompt: '细腻抒情的叙事，注重感官与心理描写，节奏舒缓'
  },
  {
    id: 'fast',
    name: '快节奏',
    description: '冲突密集，段落短，章末留钩子',
    prompt: '快节奏爽文风格，冲突密集，段落短，章末留钩子'
  },
  {
    id: 'classical',
    name: '古典雅致',
    description: '用词典雅，句式整饬',
    prompt: '古典雅致的白话文风，用词典雅，句式整饬'
  },
  {
    id: 'suspense',
    name: '悬疑冷调',
    description: '信息克制，氛围压迫，善用留白',
    prompt: '悬疑冷调叙事，信息克制，氛围压迫，善用留白'
  }
]

export function findExpert(id: string): Expert {
  return EXPERTS.find((expert) => expert.id === id) ?? EXPERTS[0]
}

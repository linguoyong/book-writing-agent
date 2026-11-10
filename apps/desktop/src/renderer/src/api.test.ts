import { afterEach, describe, expect, it, vi } from 'vitest'
import { streamChat } from './api'

afterEach(() => vi.unstubAllGlobals())

describe('stream recovery protocol', () => {
  it('keeps the specific error and completes once when the backend closes after an error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      'event: error\ndata: {"message":"模型连续 120 秒没有返回新数据"}\n\n'
    )))
    const onError = vi.fn(), onDone = vi.fn()
    await streamChat('s', 'test', 'main', [], {
      onToken: vi.fn(), onToolStart: vi.fn(), onToolEnd: vi.fn(), onError, onDone
    })
    expect(onError.mock.calls).toEqual([['模型连续 120 秒没有返回新数据']])
    expect(onDone).toHaveBeenCalledOnce()
  })

  it('forwards retry rollback without ending the stream', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      'event: token\ndata: {"text":"半截😀"}\n\n' +
      'event: retry\ndata: {"removed_chars":3,"message":"正在重试"}\n\n' +
      'event: token\ndata: {"text":"最终回答"}\n\n' +
      'event: done\ndata: {"status":"completed"}\n\n'
    )))
    const onRetry = vi.fn(), onError = vi.fn(), onDone = vi.fn(), onToken = vi.fn()
    await streamChat('s', 'test', 'side', [], {
      onRetry, onError, onDone, onToken, onToolStart: vi.fn(), onToolEnd: vi.fn()
    })
    expect(onRetry).toHaveBeenCalledWith(3, '正在重试')
    expect(onToken.mock.calls).toEqual([['半截😀'], ['最终回答']])
    expect(onError).not.toHaveBeenCalled()
    expect(onDone).toHaveBeenCalledOnce()
  })
})

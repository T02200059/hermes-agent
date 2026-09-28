import { describe, expect, it } from 'vitest'

// [owner] Ctrl+C 退出码 (§6.3)
import { exitCodeForSignal, shouldExitForSignal } from '../lib/gracefulExit.js'

describe('shouldExitForSignal', () => {
  it('ignores only the signals explicitly disabled for embedded dashboard chat', () => {
    expect(shouldExitForSignal('SIGINT', ['SIGINT'])).toBe(false)
    expect(shouldExitForSignal('SIGTERM', ['SIGINT'])).toBe(true)
    expect(shouldExitForSignal('SIGHUP', ['SIGINT'])).toBe(true)
  })
})
// [owner] Ctrl+C 退出码 (§6.3)

describe('exitCodeForSignal', () => {
  it('lets standalone Ctrl+C use the same successful status as /exit', () => {
    expect(exitCodeForSignal('SIGINT', { SIGINT: 0 })).toBe(0)
    expect(exitCodeForSignal('SIGTERM', { SIGINT: 0 })).toBe(143)
    expect(exitCodeForSignal('SIGHUP', { SIGINT: 0 })).toBe(129)
  })
})

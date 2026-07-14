/**
 * Unit tests for the translucency → opacity mapping. These assert behavior
 * contracts (invariants), not snapshot values: 0 is always opaque, the curve
 * is monotonic, garbage clamps, and — the bug this guards against — Windows
 * gets a gentler curve than macOS because it has no vibrancy to soften
 * `setOpacity`.
 */

const test = require('node:test')
const assert = require('node:assert/strict')

const {
  MACOS_OPACITY_FLOOR,
  WINDOWS_OPACITY_FLOOR,
  opacityForIntensity
} = require('./translucency.cjs')

test('0 intensity is exactly opaque on both platforms', () => {
  assert.equal(opacityForIntensity(0, false), 1)
  assert.equal(opacityForIntensity(0, true), 1)
})

test('opacity is strictly monotonic as intensity rises, on both platforms', () => {
  for (const isWindows of [false, true]) {
    let prev = 2 // higher than any valid opacity
    for (let i = 0; i <= 100; i += 5) {
      const opacity = opacityForIntensity(i, isWindows)
      assert.ok(opacity < prev, `intensity ${i} (isWindows=${isWindows}): ${opacity} not < ${prev}`)
      prev = opacity
    }
  }
})

test('full intensity hits the per-platform floor', () => {
  // approxEqual — floating point: 1 - 0.7 = 0.30000000000000004 in JS.
  const approx = (a, b) => Math.abs(a - b) < 1e-9
  assert.ok(approx(opacityForIntensity(100, false), MACOS_OPACITY_FLOOR))
  assert.ok(approx(opacityForIntensity(100, true), WINDOWS_OPACITY_FLOOR))
})

test('Windows floor is higher (gentler) than the macOS floor', () => {
  // The whole reason this split exists: Windows has no vibrancy, so the same
  // opacity reads much harsher. Windows must stay more opaque at the extreme.
  assert.ok(WINDOWS_OPACITY_FLOOR > MACOS_OPACITY_FLOOR)
})

test('at every shared grade, Windows opacity is higher (less see-through) than macOS', () => {
  for (const intensity of [5, 10, 25, 50, 75, 100]) {
    assert.ok(
      opacityForIntensity(intensity, true) > opacityForIntensity(intensity, false),
      `Windows should be less see-through than macOS at intensity ${intensity}`
    )
  }
})

test('low grades stay subtle: 5% drops only a little on each platform', () => {
  // macOS 5% → 0.965, Windows 5% → 0.988. Both must stay within 5% of opaque
  // so 5% never reads as "nearly half-transparent" (the original Windows bug).
  assert.ok(opacityForIntensity(5, false) > 0.95)
  assert.ok(opacityForIntensity(5, true) > 0.95)
})

test('garbage intensity is rejected (treated as opaque)', () => {
  for (const bad of [NaN, undefined, null, 'abc', {}, Infinity, -Infinity]) {
    assert.equal(opacityForIntensity(bad, false), 1)
    assert.equal(opacityForIntensity(bad, true), 1)
  }
})

test('out-of-range intensity clamps to [0, 100]', () => {
  // negatives → 0 (opaque); >100 → treated as 100 (the floor)
  const approx = (a, b) => Math.abs(a - b) < 1e-9
  assert.equal(opacityForIntensity(-5, false), 1)
  assert.equal(opacityForIntensity(-5, true), 1)
  assert.ok(approx(opacityForIntensity(150, false), MACOS_OPACITY_FLOOR))
  assert.ok(approx(opacityForIntensity(150, true), WINDOWS_OPACITY_FLOOR))
})

test('opacity never leaves the valid [floor, 1] range', () => {
  for (const isWindows of [false, true]) {
    const floor = isWindows ? WINDOWS_OPACITY_FLOOR : MACOS_OPACITY_FLOOR
    for (let i = 0; i <= 100; i += 5) {
      const opacity = opacityForIntensity(i, isWindows)
      assert.ok(opacity >= floor, `intensity ${i} below floor`)
      assert.ok(opacity <= 1, `intensity ${i} above opaque`)
    }
  }
})

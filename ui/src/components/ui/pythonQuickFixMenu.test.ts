import { describe, expect, it } from 'bun:test'
import { quickFixMenuPosition } from './pythonQuickFixMenu'

describe('quick fix menu position', () => {
  it('opens below the hover button when there is space', () => {
    expect(quickFixMenuPosition({ left: 120, top: 60, bottom: 80 }, 240, 100, 800, 600)).toEqual({ left: 120, top: 84 })
  })

  it('opens above near the viewport edge and keeps its width visible', () => {
    expect(quickFixMenuPosition({ left: 760, top: 550, bottom: 570 }, 240, 100, 800, 600)).toEqual({ left: 552, top: 446 })
  })
})

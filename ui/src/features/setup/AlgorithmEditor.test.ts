import { expect, test } from 'bun:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { SchemaEditor } from './AlgorithmEditor'
import type { AlgorithmInfo } from '@/types/api'

function metadata(description: string): AlgorithmInfo {
  return { name: 'SINGLE-MAKER', label: '后端名称', description: '算法原理', builtin: true, channels: null, slots: null,
    default_params: { chase_enabled: false, chase_ticks: 1 },
    params_schema: { type: 'object', properties: {
      chase_enabled: { type: 'boolean', title: '后端追单标题', description: '开关说明', default: false },
      chase_ticks: { type: 'integer', title: '后端阈值标题', description, default: 1, minimum: 0 },
    } } }
}

test('关闭追单仍完整显示可编辑字段，文案随服务端改变', () => {
  const render = (description: string) => renderToStaticMarkup(createElement(SchemaEditor, { info: metadata(description), params: { chase_enabled: false, chase_ticks: 7 }, onChange: () => {} }))
  const html = render('服务端说明甲')
  expect(html).toContain('后端追单标题')
  expect(html).toContain('后端阈值标题')
  expect(html).toContain('服务端说明甲')
  expect(html).toContain('value="7"')
  expect(html).not.toContain('disabled')
  expect(html).not.toContain('高级设置')
  expect(html).not.toContain('省成本')
  expect(render('服务端说明乙')).toContain('服务端说明乙')
})

test('服务端提示决定控件，百分比历史精度不按滑块步长取整', () => {
  const info = metadata('说明')
  info.params_schema = { type: 'object', properties: {
    mode: { type: 'string', title: '模式', enum: ['a', 'b'], 'x-control': 'cards', 'x-option-descriptions': { a: '选项独立说明' } },
    rate: { type: 'number', title: '参与率', exclusiveMinimum: 0, maximum: 1,
      'x-control': 'slider', 'x-unit': '%', 'x-display-scale': 100, 'x-display-step': 0.01, 'x-slider-min': 0.01, 'x-slider-max': 100 },
    duration: { type: 'integer', title: '时长', 'x-control': 'presets', 'x-presets': [60, 300] },
  } }
  const html = renderToStaticMarkup(createElement(SchemaEditor, { info, params: { mode: 'a', rate: 0.000012345, duration: 300 }, onChange: () => {} }))
  expect(html).toContain('role="radiogroup"')
  expect(html).toContain('选项独立说明')
  expect(html).toContain('role="slider"')
  expect(html).not.toContain('type="range"')
  expect(html).toContain('value="0.0012345"')
  expect(html).toContain('aria-pressed="true"')
  expect(html).not.toContain('role="alert"')
})

test('参与率独立 NumberFlow 保留小于一个步长的小数，无滑条', () => {
  const info = metadata('说明')
  info.params_schema = { type: 'object', properties: {
    rate: { type: 'number', title: '参与率', exclusiveMinimum: 0, maximum: 1,
      'x-control': 'numberflow', 'x-unit': '%', 'x-display-scale': 100, 'x-display-step': 1 },
  } }
  const html = renderToStaticMarkup(createElement(SchemaEditor, { info, params: { rate: 0.005 }, onChange: () => {} }))
  expect(html).toContain('number-flow-react')
  expect(html).toContain('value="0.5"')
  expect(html).toContain('增加 1 %')
  expect(html).not.toContain('role="slider"')
  expect(html).not.toContain('role="alert"')
})

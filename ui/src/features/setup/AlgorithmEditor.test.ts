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

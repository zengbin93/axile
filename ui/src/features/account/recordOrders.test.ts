import { expect, test } from 'bun:test'
import { recordOrders } from './recordOrders'

test.each([
  [{ client_order_id: 'provider-id' }, 'provider-id'],
  [{ cl_ord_id: 'gm-id' }, 'gm-id'],
  [{ client_order_id: 'provider-id', cl_ord_id: 'gm-id' }, 'provider-id'],
  [{ client_order_id: '', cl_ord_id: 'gm-id' }, 'gm-id'],
  [{}, null],
])('保留渠道客户端订单号：%j', (extra, expected) => {
  expect(recordOrders({ orders: [{ order_id: 'order', extra }] })[0].client_order_id).toBe(expected)
})

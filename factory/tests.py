from django.test import TestCase
from rest_framework.test import APIClient

from .models import Customer, Order, Paper, PaperTransaction


class ReceivePaperTests(TestCase):
    """订单领料：一键领足 / 分批领 / 库存与超领校验 / 防重复扣料"""

    def setUp(self):
        self.client = APIClient()
        self.customer = Customer.objects.create(name='测试客户')
        self.paper = Paper.objects.create(
            name='测试铜版纸', paper_type='coated', spec='157g',
            stock=1000, safety_stock=100, unit_price='0.80',
        )
        self.order = Order.objects.create(
            order_no='DD-TEST-01', customer=self.customer,
            product_name='测试画册', quantity=5000,
            paper=self.paper, paper_consumption=800,
            order_date='2026-09-01', due_date='2026-09-20',
        )
        self.url = f'/api/orders/{self.order.id}/receive_paper/'

    def receive(self, data=None):
        return self.client.post(self.url, data or {}, format='json')

    def test_receive_all_by_default(self):
        """不传数量 = 按未领量一次领完，库存扣减、流水挂到订单和纸张"""
        res = self.receive()
        self.assertEqual(res.status_code, 200)
        self.paper.refresh_from_db()
        self.assertEqual(int(self.paper.stock), 200)
        tx = PaperTransaction.objects.get(order=self.order)
        self.assertEqual(tx.tx_type, 'out')
        self.assertEqual(tx.quantity, 800)
        self.assertEqual(tx.paper, self.paper)
        self.assertEqual(res.data['received_qty'], 800)
        self.assertEqual(res.data['remaining_qty'], 0)
        self.assertEqual(res.data['paper_stock'], 200)

    def test_receive_in_batches(self):
        """分批领料：已领累计、未领递减"""
        res = self.receive({'quantity': 300})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['received_qty'], 300)
        self.assertEqual(res.data['remaining_qty'], 500)

        res = self.receive({'quantity': 500})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['received_qty'], 800)
        self.assertEqual(res.data['remaining_qty'], 0)
        self.paper.refresh_from_db()
        self.assertEqual(int(self.paper.stock), 200)
        self.assertEqual(PaperTransaction.objects.filter(order=self.order).count(), 2)

    def test_receive_exceeding_remaining_rejected(self):
        """超出未领数量：拦截并提示已领/未领，库存不变"""
        self.receive({'quantity': 300})
        res = self.receive({'quantity': 600})
        self.assertEqual(res.status_code, 400)
        self.assertIn('已领 300 张', res.data['detail'])
        self.assertIn('未领 500 张', res.data['detail'])
        self.assertIn('最多可领 500 张', res.data['detail'])
        self.paper.refresh_from_db()
        self.assertEqual(int(self.paper.stock), 700)

    def test_receive_insufficient_stock_reports_shortage(self):
        """库存不足：提示还差多少张，库存不变"""
        self.paper.stock = 100
        self.paper.save()
        res = self.receive({'quantity': 300})
        self.assertEqual(res.status_code, 400)
        self.assertIn('还差 200 张', res.data['detail'])
        self.paper.refresh_from_db()
        self.assertEqual(int(self.paper.stock), 100)
        self.assertFalse(PaperTransaction.objects.filter(order=self.order).exists())

    def test_repeat_receive_after_fulfilled_rejected(self):
        """领足后重复领料：拦截，防止同一订单扣两遍料"""
        res = self.receive()
        self.assertEqual(res.status_code, 200)
        res = self.receive()
        self.assertEqual(res.status_code, 400)
        self.assertIn('已全部领完', res.data['detail'])
        self.assertIn('已领 800 张', res.data['detail'])
        self.paper.refresh_from_db()
        self.assertEqual(int(self.paper.stock), 200)
        self.assertEqual(PaperTransaction.objects.filter(order=self.order).count(), 1)

    def test_receive_without_consumption_rejected(self):
        """订单未填用纸量：提示先维护"""
        self.order.paper_consumption = 0
        self.order.save()
        res = self.receive()
        self.assertEqual(res.status_code, 400)
        self.assertIn('未填写用纸量', res.data['detail'])

    def test_receive_invalid_quantity(self):
        res = self.receive({'quantity': 'abc'})
        self.assertEqual(res.status_code, 400)
        res = self.receive({'quantity': 0})
        self.assertEqual(res.status_code, 400)
        self.assertFalse(PaperTransaction.objects.filter(order=self.order).exists())

    def test_detail_contains_receive_info(self):
        """订单详情：已领/未领/当前库存/领料记录"""
        self.receive({'quantity': 300})
        res = self.client.get(f'/api/orders/{self.order.id}/')
        self.assertEqual(res.data['received_qty'], 300)
        self.assertEqual(res.data['remaining_qty'], 500)
        self.assertEqual(res.data['paper_stock'], 700)
        self.assertEqual(len(res.data['paper_transactions']), 1)
        self.assertEqual(res.data['paper_transactions'][0]['quantity'], 300)
        self.assertEqual(res.data['paper_transactions'][0]['order_no'], 'DD-TEST-01')

    def test_list_contains_receive_summary(self):
        """订单列表：已领/未领差额"""
        self.receive({'quantity': 300})
        res = self.client.get('/api/orders/')
        row = next(o for o in res.data if o['id'] == self.order.id)
        self.assertEqual(row['received_qty'], 300)
        self.assertEqual(row['remaining_qty'], 500)

    def test_manual_stock_out_linked_to_order_counts_as_received(self):
        """纸张页手工出库并关联订单的，同样计入已领，不会重复领"""
        self.client.post(f'/api/papers/{self.paper.id}/stock_out/',
                         {'quantity': 300, 'order': self.order.id}, format='json')
        res = self.client.get(f'/api/orders/{self.order.id}/')
        self.assertEqual(res.data['received_qty'], 300)
        # 再一键领足只领剩余 500，不会按 800 重复扣
        res = self.receive()
        self.assertEqual(res.status_code, 200)
        self.paper.refresh_from_db()
        self.assertEqual(int(self.paper.stock), 200)

from django.db.models import Sum
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


class PaperStockOutTests(TestCase):
    """纸张页出库：订单未领量校验 / 用纸一致性 / 库存原子扣减"""

    def setUp(self):
        self.client = APIClient()
        self.customer = Customer.objects.create(name='测试客户')
        self.paper = Paper.objects.create(
            name='测试铜版纸', paper_type='coated', spec='157g',
            stock=1000, safety_stock=0, unit_price='0.80',
        )
        self.other_paper = Paper.objects.create(
            name='测试胶版纸', paper_type='offset', spec='80g',
            stock=5000, safety_stock=0, unit_price='0.30',
        )
        self.order = Order.objects.create(
            order_no='DD-OUT-01', customer=self.customer,
            product_name='测试画册', quantity=5000,
            paper=self.paper, paper_consumption=800,
            order_date='2026-09-01', due_date='2026-09-20',
        )

    def out(self, data, paper=None):
        paper = paper or self.paper
        return self.client.post(f'/api/papers/{paper.id}/stock_out/', data, format='json')

    def stock(self, paper=None):
        (paper or self.paper).refresh_from_db()
        return int((paper or self.paper).stock)

    def test_stock_out_linked_within_remaining(self):
        """关联订单且在未领量内：正常出库并计入已领"""
        res = self.out({'quantity': 300, 'order': self.order.id})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.stock(), 700)
        res = self.client.get(f'/api/orders/{self.order.id}/')
        self.assertEqual(res.data['received_qty'], 300)
        self.assertEqual(res.data['remaining_qty'], 500)

    def test_stock_out_exceeding_order_remaining_rejected(self):
        """纸张页出库超出订单未领量：拦截，库存与流水不变"""
        res = self.out({'quantity': 600, 'order': self.order.id})
        self.assertEqual(res.status_code, 200)
        res = self.out({'quantity': 300, 'order': self.order.id})
        self.assertEqual(res.status_code, 400)
        self.assertIn('未领 200 张', res.data['detail'])
        self.assertIn('最多可领 200 张', res.data['detail'])
        self.assertEqual(self.stock(), 400)
        self.assertEqual(PaperTransaction.objects.filter(order=self.order).count(), 1)

    def test_stock_out_fully_received_order_rejected(self):
        """订单已领完后，纸张页再出库同一订单：拦截，防止重复扣料"""
        res = self.out({'quantity': 800, 'order': self.order.id})
        self.assertEqual(res.status_code, 200)
        res = self.out({'quantity': 100, 'order': self.order.id})
        self.assertEqual(res.status_code, 400)
        self.assertIn('已全部领完', res.data['detail'])
        self.assertEqual(self.stock(), 200)
        self.assertEqual(PaperTransaction.objects.filter(order=self.order).count(), 1)

    def test_stock_out_mismatched_paper_rejected(self):
        """给订单出库别的纸张：拦截，两边库存与流水都不变"""
        res = self.out({'quantity': 100, 'order': self.order.id}, paper=self.other_paper)
        self.assertEqual(res.status_code, 400)
        self.assertIn('不一致', res.data['detail'])
        self.assertEqual(self.stock(), 1000)
        self.assertEqual(self.stock(self.other_paper), 5000)
        self.assertFalse(PaperTransaction.objects.filter(order=self.order).exists())

    def test_mismatched_transaction_not_counted_as_received(self):
        """历史遗留的错纸流水：不计入已领，详情领料记录也不显示"""
        PaperTransaction.objects.create(
            paper=self.other_paper, tx_type='out', quantity=200,
            order=self.order, tx_date='2026-09-02', note='错挂的流水',
        )
        res = self.client.get(f'/api/orders/{self.order.id}/')
        self.assertEqual(res.data['received_qty'], 0)
        self.assertEqual(res.data['remaining_qty'], 800)
        self.assertEqual(len(res.data['paper_transactions']), 0)
        # 列表口径一致
        res = self.client.get('/api/orders/')
        row = next(o for o in res.data if o['id'] == self.order.id)
        self.assertEqual(row['received_qty'], 0)
        # 一键领足仍按 800 领，不受错挂流水影响
        res = self.client.post(f'/api/orders/{self.order.id}/receive_paper/', {}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['received_qty'], 800)

    def test_stock_out_without_order_still_allowed(self):
        """不关联订单的普通出库：不受影响"""
        res = self.out({'quantity': 400})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.stock(), 600)
        tx = PaperTransaction.objects.get(paper=self.paper, tx_type='out')
        self.assertIsNone(tx.order)

    def test_stock_out_insufficient_stock_reports_shortage(self):
        """库存不足：提示还差多少张，库存与流水不变"""
        res = self.out({'quantity': 1500})
        self.assertEqual(res.status_code, 400)
        self.assertIn('还差 500 张', res.data['detail'])
        self.assertEqual(self.stock(), 1000)
        self.assertFalse(PaperTransaction.objects.filter(paper=self.paper).exists())

    def test_stock_out_order_not_found(self):
        res = self.out({'quantity': 100, 'order': 99999})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.stock(), 1000)

    def test_sequential_outs_each_decrement_stock(self):
        """连续出库：每笔都扣库存，库存 = 期初 - 流水合计"""
        self.out({'quantity': 100})
        self.out({'quantity': 250})
        self.assertEqual(self.stock(), 650)
        total = (PaperTransaction.objects
                 .filter(paper=self.paper, tx_type='out')
                 .aggregate(s=Sum('quantity'))['s'])
        self.assertEqual(1000 - total, self.stock())

    def test_stock_in_then_out_consistent(self):
        """入库用原子累加：入出库交替后库存与流水勾稽"""
        self.client.post(f'/api/papers/{self.paper.id}/stock_in/',
                         {'quantity': 500}, format='json')
        self.out({'quantity': 300})
        self.out({'quantity': 200})
        self.assertEqual(self.stock(), 1000)
        ins = (PaperTransaction.objects.filter(paper=self.paper, tx_type='in')
               .aggregate(s=Sum('quantity'))['s'])
        outs = (PaperTransaction.objects.filter(paper=self.paper, tx_type='out')
                .aggregate(s=Sum('quantity'))['s'])
        self.assertEqual(1000 + ins - outs, self.stock())

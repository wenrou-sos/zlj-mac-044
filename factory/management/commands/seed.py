from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q, Sum

from factory.models import (
    Customer,
    Machine,
    Order,
    Paper,
    PaperBatch,
    PaperTransaction,
    ReworkRecord,
    Schedule,
)

Q_IN = Q(tx_type=PaperTransaction.TxType.IN)
Q_OUT = Q(tx_type=PaperTransaction.TxType.OUT)


class Command(BaseCommand):
    help = '生成印刷厂演示样例数据（可重复执行：先清空业务数据再重建）'

    @transaction.atomic
    def handle(self, *args, **options):
        # 清空业务数据（保留用户/权限）
        ReworkRecord.objects.all().delete()
        Schedule.objects.all().delete()
        Order.objects.all().delete()
        PaperTransaction.objects.all().delete()
        PaperBatch.objects.all().delete()
        Paper.objects.all().delete()
        Machine.objects.all().delete()
        Customer.objects.all().delete()

        today = date.today()
        self.stdout.write(f'基准日期：{today}')

        # ---------------- 客户 ----------------
        customers = [
            Customer.objects.create(name='翰林文化传播有限公司', contact='王敏', phone='13800001111'),
            Customer.objects.create(name='绿叶化妆品股份有限公司', contact='李强', phone='13800002222'),
            Customer.objects.create(name='市教育局教材中心', contact='赵老师', phone='13800003333'),
            Customer.objects.create(name='锦华食品包装厂', contact='陈芳', phone='13800004444'),
            Customer.objects.create(name='时代广告传媒', contact='刘洋', phone='13800005555'),
        ]

        # ---------------- 纸张 ----------------
        papers_data = [
            # 名称, 类型, 规格, 目标库存, 安全库存, 单价
            ('金东铜版纸', 'coated', '157g/889×1194', 1200, 3000, '0.85'),
            ('金东铜版纸', 'coated', '200g/889×1194', 8600, 3000, '1.05'),
            ('亚太胶版纸', 'offset', '80g/787×1092', 42000, 10000, '0.32'),
            ('亚太胶版纸', 'offset', '70g/787×1092', 36000, 10000, '0.28'),
            ('白卡', 'whiteboard', '300g/889×1194', 9500, 4000, '1.20'),
            ('牛皮纸', 'kraft', '120g/889×1194', 15000, 5000, '0.65'),
            ('星采特种纸', 'special', '250g/珠光/787×1092', 3200, 1500, '2.40'),
        ]
        papers = {}
        for name, ptype, spec, stock, safety, price in papers_data:
            p = Paper.objects.create(
                name=name, paper_type=ptype, spec=spec,
                stock=0, safety_stock=safety, unit_price=price,
            )
            papers[spec] = p

        # ---------------- 机台 ----------------
        machines = [
            Machine.objects.create(name='海德堡CD102-1号机', machine_type='对开四色胶印机', status='running'),
            Machine.objects.create(name='海德堡SM52-2号机', machine_type='四开四色胶印机', status='running'),
            Machine.objects.create(name='小森LS440-3号机', machine_type='对开四色胶印机', status='idle'),
            Machine.objects.create(name='罗兰700-4号机', machine_type='对开五色胶印机', status='maintenance'),
            Machine.objects.create(name='马天尼胶订线', machine_type='全自动胶装联动线', status='running'),
        ]

        # ---------------- 订单 ----------------
        # (编号, 客户idx, 产品, 数量, 纸张spec, 用纸量, 状态, 下单偏移, 交期偏移)
        orders_spec = [
            ('DD20260901-01', 0, '《中国古典文学鉴赏》画册', 5000, '157g/889×1194', 6200,
             'rework', -12, -1),
            ('DD20260905-02', 1, '绿叶护肤精华礼盒包装盒', 8000, '300g/889×1194', 8300,
             'printing', -9, 2),
            ('DD20260908-03', 2, '小学三年级《美术》教材', 20000, '70g/787×1092', 26000,
             'binding', -6, 4),
            ('DD20260910-04', 4, '秋季房交会宣传海报', 12000, '200g/889×1194', 6500,
             'prepress', -4, 5),
            ('DD20260911-05', 3, '月饼礼盒手提袋', 15000, '120g/889×1194', 9000,
             'printing', -3, 8),
            ('DD20260912-06', 1, '品牌产品手册', 6000, '157g/889×1194', 4800,
             'pending', -2, 12),
            ('DD20260828-07', 2, '《校园安全知识读本》', 10000, '80g/787×1092', 13500,
             'completed', -17, -6),
            ('DD20260913-08', 0, '企业年度精装纪念册', 2000, '250g/珠光/787×1092', 3600,
             'prepress', -1, 1),
        ]

        order_objs = []
        for (no, ci, product, qty, pspec, consumption, status, od_off, due_off) in orders_spec:
            o = Order.objects.create(
                order_no=no, customer=customers[ci], product_name=product,
                quantity=qty, paper=papers[pspec], paper_consumption=consumption,
                status=status, order_date=today + timedelta(days=od_off),
                due_date=today + timedelta(days=due_off),
            )
            order_objs.append(o)

        o1, o2, o3, o4, o5, o6, o7, o8 = order_objs

        # ---------------- 工序进度 ----------------
        def set_progress(order, prepress, printing, binding):
            p = order.progress
            (p.prepress_status, p.prepress_progress, p.prepress_note) = prepress
            (p.printing_status, p.printing_progress, p.printing_note) = printing
            (p.binding_status, p.binding_progress, p.binding_note) = binding
            p.save()
            p.sync_order_status()

        # 订单1：印刷色差返工（逾期）
        set_progress(o1,
                     ('done', 100, '制版校对完成'),
                     ('rework', 70, '首批封面偏红，停机调墨返工'),
                     ('not_started', 0, ''))
        # 订单2：印刷中，交期紧急（2天）
        set_progress(o2,
                     ('done', 100, '刀版与色彩管理完成'),
                     ('in_progress', 55, '已完成正面印刷，待印反面'),
                     ('not_started', 0, ''))
        # 订单3：装订中
        set_progress(o3,
                     ('done', 100, '拼版打样确认'),
                     ('done', 100, '书芯内页全部印完'),
                     ('in_progress', 40, '胶装进行中，待三面切'))
        # 订单4：印前中
        set_progress(o4,
                     ('in_progress', 60, '正在拼大版与数码打样'),
                     ('not_started', 0, ''),
                     ('not_started', 0, ''))
        # 订单5：印刷中
        set_progress(o5,
                     ('done', 100, '纸袋展开刀模确认'),
                     ('in_progress', 30, '1号机上机，专色调试中'),
                     ('not_started', 0, ''))
        # 订单6：待排产
        set_progress(o6,
                     ('not_started', 0, ''),
                     ('not_started', 0, ''),
                     ('not_started', 0, ''))
        # 订单7：已完成
        set_progress(o7,
                     ('done', 100, ''),
                     ('done', 100, ''),
                     ('done', 100, '骑订入库'))
        o7.completed_date = today - timedelta(days=5)
        o7.save()
        # 订单8：印前中，交期明天
        set_progress(o8,
                     ('in_progress', 80, '封面特种纸工艺确认中（烫银+UV）'),
                     ('not_started', 0, ''),
                     ('not_started', 0, ''))

        # ---------------- 排产计划 ----------------
        schedules = [
            # 订单1：前期排产已完成 + 今日返工排产
            (o1, machines[0], today - timedelta(days=4), '白班', 3000, 3000, True),
            (o1, machines[0], today, '夜班', 2000, 0, False),
            # 订单2：今日在2号机
            (o2, machines[1], today - timedelta(days=1), '白班', 4000, 4200, True),
            (o2, machines[1], today, '白班', 4000, 3000, False),
            # 订单3：印刷已完成，胶订线今日+明日
            (o3, machines[4], today, '白班', 10000, 4000, False),
            (o3, machines[4], today + timedelta(days=1), '白班', 10000, 0, False),
            # 订单5：1号机今日下午/明日
            (o5, machines[0], today + timedelta(days=1), '白班', 8000, 0, False),
            # 订单4：印后两天上机
            (o4, machines[2], today + timedelta(days=2), '白班', 12000, 0, False),
        ]
        for (order, machine, d, shift, plan, actual, done) in schedules:
            Schedule.objects.create(
                order=order, machine=machine, planned_date=d, shift=shift,
                planned_qty=plan, actual_qty=actual, done=done,
            )

        # ---------------- 返工单 ----------------
        rw1 = ReworkRecord.objects.create(
            order=o1, stage='printing', reason='color', qty=1500,
            status='processing', handler='张师傅（领机）',
            found_at=today - timedelta(days=1),
            description='封面大红色实地批次与签样相比偏红约 ΔE 3.2，客户驻厂代表拒收。',
        )
        rw1.result = '已重新调配专色油墨，清洗墨辊后重新上机，预计今晚夜班完成。'
        rw1.save()

        ReworkRecord.objects.create(
            order=o7, stage='binding', reason='binding', qty=200,
            status='closed', handler='李班长',
            found_at=today - timedelta(days=8),
            closed_at=today - timedelta(days=6),
            description='部分读本骑马钉钉脚偏移，存在散页风险。',
            result='200 本全部重订，全检后入库；已对装订机订头做校准保养。',
        )

        # ---------------- 纸张批次入库 ----------------
        # 批次定义：(到货偏移天数, 保质期天数 None=无, 入库量)
        # 刻意构造 已过期 / 临期(≤30天) / 正常 三种效期，便于展示 FEFO 与预警
        batch_plans = {
            '157g/889×1194': [
                (-400, 365, 6600),   # 已过期（到期日 = 今天-35天），领料 6200 后余 400
                (-60, 72, 800),      # 临期（到期日 = 今天+12天），未动用
            ],
            '200g/889×1194': [
                (-380, 365, 1500),   # 已过期，出库时被 FEFO 优先消耗完
                (-20, 42, 5100),     # 临期（到期日 = 今天+22天），余 100
                (-10, 365, 8500),    # 正常
            ],
            '80g/787×1092': [
                (-420, 365, 10000),  # 已过期，全部被早期领料消耗
                (-25, 45, 18000),    # 临期（到期日 = 今天+20天），余 14500
                (-8, 365, 27500),    # 正常
            ],
            '70g/787×1092': [
                (-18, 40, 27000),    # 临期（到期日 = 今天+22天），余 1000
                (-6, 365, 35000),    # 正常
            ],
            '300g/889×1194': [
                (-120, 90, 1800),    # 已过期（到期日 = 今天-30天），被消耗完
                (-15, 35, 7000),     # 临期（到期日 = 今天+20天），余 500
                (-5, 365, 9000),     # 正常
            ],
            '120g/889×1194': [
                (-30, 50, 9500),     # 临期（到期日 = 今天+20天），余 500
                (-10, 365, 14500),   # 正常
            ],
            '250g/珠光/787×1092': [
                (-200, 190, 4000),   # 已过期（到期日 = 今天-10天），领料 3600 后余 400
                (-30, 45, 1800),     # 临期（到期日 = 今天+15天），未动用
                (-5, 540, 1000),     # 正常
            ],
        }

        batch_seq = {}

        def create_batches(spec):
            """按方案创建批次并登记入库流水，返回批次列表（按 FEFO 顺序）"""
            paper = papers[spec]
            created = []
            for idx, (arr_off, shelf_days, in_qty) in enumerate(batch_plans[spec], start=1):
                arrival = today + timedelta(days=arr_off)
                expiry = arrival + timedelta(days=shelf_days) if shelf_days else None
                batch_no = f'B{arrival.strftime("%Y%m%d")}-{idx:02d}'
                batch = PaperBatch.objects.create(
                    paper=paper, batch_no=batch_no,
                    arrival_date=arrival, expiry_date=expiry, note='采购入库',
                )
                PaperTransaction.objects.create(
                    paper=paper, batch=batch, tx_type='in', quantity=in_qty,
                    tx_date=arrival, note='采购入库',
                )
                created.append(batch)
            # FEFO：到期日早的优先，无保质期排最后
            created.sort(key=lambda b: (b.expiry_date is None,
                                        b.expiry_date or date.max,
                                        b.arrival_date, b.id))
            batch_seq[spec] = created
            return created

        for spec in batch_plans:
            create_batches(spec)

        # ---------------- 用纸出库（按 FEFO 从各批次扣减） ----------------
        stock_out_orders = [o1, o2, o3, o4, o5, o7, o8]
        # 按领料日期先后排序，便于按批次余量顺序消耗
        stock_out_orders.sort(key=lambda o: (o.order_date + timedelta(days=1), o.id))
        for order in stock_out_orders:
            paper = order.paper
            qty = order.paper_consumption
            tx_d = order.order_date + timedelta(days=1)
            left = qty
            for batch in batch_seq[paper.spec]:
                if left <= 0:
                    break
                # 实时计算该批次当前余量
                agg = batch.transactions.aggregate(
                    ins=Sum('quantity', filter=Q_IN),
                    outs=Sum('quantity', filter=Q_OUT),
                )
                remaining = (agg['ins'] or 0) - (agg['outs'] or 0)
                take = min(remaining, left)
                if take <= 0:
                    continue
                PaperTransaction.objects.create(
                    paper=paper, batch=batch, tx_type='out', quantity=take,
                    order=order, tx_date=tx_d, note=f'{order.order_no} 生产领料',
                )
                left -= take
            if left > 0:
                self.stdout.write(self.style.WARNING(
                    f'{paper.spec} 批次入库量不足以支撑 {order.order_no} 领料，缺口 {left} 张'))

        # 库存 = 入库合计 - 出库合计，按流水回填保证账实勾稽
        for paper in papers.values():
            agg = paper.transactions.aggregate(
                ins=Sum('quantity', filter=Q_IN),
                outs=Sum('quantity', filter=Q_OUT),
            )
            paper.stock = (agg['ins'] or 0) - (agg['outs'] or 0)
            paper.save(update_fields=['stock'])

        self.stdout.write(self.style.SUCCESS(
            f'样例数据生成完成：客户 {len(customers)} 家、纸张 {len(papers_data)} 种'
            f'（批次 {PaperBatch.objects.count()} 个）、'
            f'机台 {len(machines)} 台、订单 {len(orders_spec)} 个、'
            f'排产 {len(schedules)} 条、返工单 2 张'
        ))

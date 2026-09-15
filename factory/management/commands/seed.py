from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from factory.models import (
    Customer,
    Machine,
    Order,
    Paper,
    PaperTransaction,
    ReworkRecord,
    Schedule,
)


class Command(BaseCommand):
    help = '生成印刷厂演示样例数据（可重复执行：先清空业务数据再重建）'

    @transaction.atomic
    def handle(self, *args, **options):
        # 清空业务数据（保留用户/权限）
        ReworkRecord.objects.all().delete()
        Schedule.objects.all().delete()
        Order.objects.all().delete()
        PaperTransaction.objects.all().delete()
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
            # 名称, 类型, 规格, 库存, 安全库存, 单价
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
                stock=stock, safety_stock=safety, unit_price=price,
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
        # (订单, 工序, 原因, 机台, 返工份数, 补投张数, 状态, 发现偏移, 闭环偏移, 责任人, 描述, 结果)
        def make_rework(order, stage, reason, machine, qty, sheets, status,
                        found_off, closed_off, handler, desc, result=''):
            rw = ReworkRecord.objects.create(
                order=order, stage=stage, reason=reason, machine=machine,
                qty=qty, makeup_sheets=sheets, status=status, handler=handler,
                found_at=today + timedelta(days=found_off),
                closed_at=today + timedelta(days=closed_off) if closed_off is not None else None,
                description=desc, result=result,
            )
            # 损耗金额按订单用纸单价 × 补投张数折算
            rw.loss_amount = rw.calc_loss_amount()
            rw.save(update_fields=['loss_amount'])
            return rw

        rw1 = make_rework(
            o1, 'printing', 'color', machines[0], 1500, 800, 'processing',
            -1, None, '张师傅（领机）',
            '封面大红色实地批次与签样相比偏红约 ΔE 3.2，客户驻厂代表拒收。',
            '已重新调配专色油墨，清洗墨辊后重新上机，预计今晚夜班完成。')

        make_rework(
            o7, 'binding', 'binding', machines[4], 200, 260, 'closed',
            -8, -6, '李班长',
            '部分读本骑马钉钉脚偏移，存在散页风险。',
            '200 本全部重订，全检后入库；已对装订机订头做校准保养。')

        # 以下为近两个月的历史返工单（均已闭环），用于看板损耗汇总统计
        make_rework(
            o2, 'printing', 'register', machines[1], 800, 300, 'closed',
            -7, -6, '王领机',
            '包装盒正面图案与刀模线套印偏差超 0.3mm，模切后白边明显。',
            '重新校准规矩与拉规定位，补印 300 张后复检合格。')

        make_rework(
            o3, 'printing', 'scratch', machines[2], 1200, 1500, 'closed',
            -12, -10, '赵师傅',
            '内页第 3 帖出现周期性橡皮布压痕和脏点，疑似橡皮布松动。',
            '更换橡皮布并清洗滚筒，补投 1500 张重印第 3 帖。')

        make_rework(
            o5, 'printing', 'color', machines[0], 500, 200, 'closed',
            -5, -4, '张师傅（领机）',
            '手提袋专金实地墨色不均，局部发花。',
            '调整专墨配比与压力，补印 200 张后色差恢复达标。')

        make_rework(
            o4, 'prepress', 'material', None, 600, 100, 'closed',
            -18, -17, '印前-孙工',
            '200g 铜版纸裁切尺寸偏差 2mm，拼版后无法上机，早期单据未登记机台。',
            '退回纸仓重新裁切，补投 100 张；已与纸仓核对裁切公差。')

        make_rework(
            o8, 'printing', 'other', machines[1], 100, 150, 'closed',
            -15, -14, '王领机',
            '特种纸烫银后局部附着力不足，UV 工序返工。',
            '调整 UV 灯功率与走纸速度，补投 150 张重新过 UV。')

        make_rework(
            o7, 'binding', 'scratch', machines[4], 300, 250, 'closed',
            -12, -11, '李班长',
            '读本封面覆膜后表面划伤，疑为胶订线导轨毛刺。',
            '打磨导轨并包覆防护条，补投 250 张封面重做。')

        rework_count = ReworkRecord.objects.count()

        # ---------------- 用纸出库流水 ----------------
        for order in [o1, o2, o3, o4, o5, o7, o8]:
            PaperTransaction.objects.create(
                paper=order.paper, tx_type='out', quantity=order.paper_consumption,
                order=order, tx_date=order.order_date + timedelta(days=1),
                note=f'{order.order_no} 生产领料',
            )

        # 期初入库 = 当前库存 + 累计出库，保证库存账实勾稽
        for paper in papers.values():
            from django.db.models import Sum
            total_out = (paper.transactions.filter(tx_type='out')
                         .aggregate(s=Sum('quantity'))['s'] or 0)
            PaperTransaction.objects.create(
                paper=paper, tx_type='in', quantity=int(paper.stock) + total_out,
                tx_date=today - timedelta(days=30), note='期初库存',
            )

        self.stdout.write(self.style.SUCCESS(
            f'样例数据生成完成：客户 {customers.__len__()} 家、纸张 {len(papers_data)} 种、'
            f'机台 {len(machines)} 台、订单 {len(orders_spec)} 个、'
            f'排产 {len(schedules)} 条、返工单 {rework_count} 张'
        ))

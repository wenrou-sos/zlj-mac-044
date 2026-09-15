import time
from functools import wraps

from django.db import OperationalError, transaction
from django.db.models import Count, F, IntegerField, Q, Sum, Value
from django.db.models.functions import Coalesce
from .models import today
from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.decorators import action

from .models import (
    Customer,
    Machine,
    Order,
    Paper,
    PaperTransaction,
    ProcessProgress,
    ReworkRecord,
    Schedule,
)
from .serializers import (
    CustomerSerializer,
    MachineSerializer,
    OrderListSerializer,
    OrderSerializer,
    PaperSerializer,
    PaperTransactionSerializer,
    ProcessProgressSerializer,
    ReworkSerializer,
    ScheduleSerializer,
)


def retry_on_db_lock(times=3, delay=0.05):
    """SQLite 下并发写冲突（database is locked）时整事务重试，
    让后到的事务读到已提交数据后按业务校验正常返回（如"已全部领完"），
    而不是向用户抛 500。"""
    def deco(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(times):
                try:
                    return func(*args, **kwargs)
                except OperationalError as e:
                    if 'locked' not in str(e).lower() or attempt == times - 1:
                        raise
                    time.sleep(delay * (attempt + 1))
        return wrapper
    return deco


class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all().order_by('name')
    serializer_class = CustomerSerializer


class PaperViewSet(viewsets.ModelViewSet):
    queryset = Paper.objects.all().order_by('name')
    serializer_class = PaperSerializer

    @staticmethod
    def _parse_qty(request):
        """解析出入库数量；非法或为空时抛出 ValidationError(400)"""
        raw = request.data.get('quantity')
        if raw in (None, ''):
            from rest_framework.serializers import ValidationError
            raise ValidationError({'quantity': '数量不能为空'})
        try:
            qty = int(raw)
        except (TypeError, ValueError):
            from rest_framework.serializers import ValidationError
            raise ValidationError({'quantity': '数量必须为整数'})
        return qty

    @action(detail=True, methods=['post'])
    @retry_on_db_lock()
    def stock_in(self, request, pk=None):
        """入库：增加库存并写流水"""
        paper = self.get_object()
        qty = self._parse_qty(request)
        if qty <= 0:
            return Response({'detail': '入库数量必须大于 0'}, status=400)
        with transaction.atomic():
            # F 表达式原子累加，并发入库不会互相覆盖
            Paper.objects.filter(pk=paper.pk).update(stock=F('stock') + qty)
            PaperTransaction.objects.create(
                paper=paper, tx_type=PaperTransaction.TxType.IN, quantity=qty,
                tx_date=today(), note=request.data.get('note') or '采购入库',
            )
        paper.refresh_from_db()
        return Response(PaperSerializer(paper).data)

    @action(detail=True, methods=['post'])
    @retry_on_db_lock()
    def stock_out(self, request, pk=None):
        """出库（领料）：扣减库存并写流水。

        关联订单时校验：纸张必须与订单用纸一致、不得超出订单未领数量，
        防止同一订单被重复扣料；库存扣减为单条 SQL 原子操作，
        两笔出库同时提交也不会只扣一笔。
        """
        paper = self.get_object()
        qty = self._parse_qty(request)
        if qty <= 0:
            return Response({'detail': '出库数量必须大于 0'}, status=400)
        order_id = request.data.get('order')

        def reject(message):
            # atomic 块内 return 会正常提交而非回滚，必须显式标记回滚，
            # 否则校验失败时上面的库存扣减会被一并提交
            transaction.set_rollback(True)
            return Response({'detail': message}, status=400)

        with transaction.atomic():
            # 条件原子扣减：stock>=qty 的判断与扣减在同一条 UPDATE 内完成，
            # 并发请求在数据库层串行，库存与流水始终一致
            updated = (Paper.objects.filter(pk=paper.pk, stock__gte=qty)
                       .update(stock=F('stock') - qty))
            if not updated:
                stock = (Paper.objects.filter(pk=paper.pk)
                         .values_list('stock', flat=True).first())
                return reject(f'库存不足：当前库存 {int(stock)} 张，'
                              f'本次需出库 {qty} 张，还差 {qty - int(stock)} 张')

            order = None
            if order_id:
                # 校验在扣减之后、提交之前：任一校验失败整体回滚，库存不会被扣
                order = (Order.objects.filter(pk=order_id)
                         .select_related('paper').first())
                if order is None:
                    return reject('关联订单不存在')
                if order.paper_id != paper.id:
                    return reject(f'订单 {order.order_no} 的用纸是「{order.paper}」，'
                                  f'与当前出库纸张「{paper}」不一致，请核对后再出库')
                if order.paper_consumption <= 0:
                    return reject(f'订单 {order.order_no} 未填写用纸量，不能关联领料出库')
                received = (PaperTransaction.objects
                            .filter(order=order, paper=paper,
                                    tx_type=PaperTransaction.TxType.OUT)
                            .aggregate(s=Sum('quantity'))['s'] or 0)
                remaining = order.paper_consumption - received
                if remaining <= 0:
                    return reject(f'订单 {order.order_no} 用纸量 {order.paper_consumption} 张'
                                  f'已全部领完（已领 {received} 张），请勿重复领料')
                if qty > remaining:
                    return reject(f'超出订单 {order.order_no} 未领数量：'
                                  f'用纸量 {order.paper_consumption} 张，已领 {received} 张，'
                                  f'未领 {remaining} 张，本次最多可领 {remaining} 张')

            PaperTransaction.objects.create(
                paper=paper, tx_type=PaperTransaction.TxType.OUT, quantity=qty,
                order=order, tx_date=today(),
                note=request.data.get('note') or '生产领料',
            )
        paper.refresh_from_db()
        return Response(PaperSerializer(paper).data)


class MachineViewSet(viewsets.ModelViewSet):
    queryset = Machine.objects.all().order_by('name')
    serializer_class = MachineSerializer


class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer

    def get_queryset(self):
        # 注解已领料张数（该订单、且纸张与订单用纸一致的出库流水合计），避免列表逐单查询
        return Order.objects.select_related('customer', 'paper', 'progress').annotate(
            received_qty_annotated=Coalesce(
                Sum('papertransaction__quantity',
                    filter=Q(papertransaction__tx_type=PaperTransaction.TxType.OUT)
                           & Q(papertransaction__paper_id=F('paper_id'))),
                Value(0), output_field=IntegerField(),
            )
        )

    def get_serializer_class(self):
        if self.action == 'list':
            return OrderListSerializer
        return OrderSerializer

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        status = request.query_params.get('status')
        warning = request.query_params.get('warning')
        keyword = request.query_params.get('keyword')
        customer_id = request.query_params.get('customer')
        if status:
            qs = qs.filter(status=status)
        if customer_id:
            qs = qs.filter(customer_id=customer_id)
        if keyword:
            qs = qs.filter(order_no__icontains=keyword) | qs.filter(product_name__icontains=keyword)
        if warning and warning != 'all':
            cur = today()
            active = qs.exclude(status=Order.Status.COMPLETED)
            ids = []
            for o in active:
                days = (o.due_date - cur).days
                if warning == 'overdue' and days < 0:
                    ids.append(o.id)
                elif warning == 'urgent' and 0 <= days <= 2:
                    ids.append(o.id)
                elif warning == 'warning' and 3 <= days <= 5:
                    ids.append(o.id)
            qs = qs.filter(id__in=ids)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get', 'patch'])
    def progress(self, request, pk=None):
        """读取/更新订单三道工序进度"""
        order = self.get_object()
        if request.method == 'GET':
            return Response(ProcessProgressSerializer(order.progress).data)
        serializer = ProcessProgressSerializer(
            order.progress, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    @retry_on_db_lock()
    def receive_paper(self, request, pk=None):
        """订单领料：按用纸量从订单对应纸张出库。

        - 不传 quantity 时默认一次领完全部未领；传 quantity 则分批领料
        - 超出未领数量直接拦截，防止同一订单重复扣料
        - 库存不足时返回还差多少张
        每次领料自动写流水并关联订单与纸张。
        """
        self.get_object()  # 404 检查
        with transaction.atomic():
            order = (Order.objects.select_for_update()
                     .select_related('paper').get(pk=self.kwargs['pk']))
            paper = Paper.objects.select_for_update().get(pk=order.paper_id)

            if order.paper_consumption <= 0:
                return Response({'detail': '该订单未填写用纸量，请先在订单中维护用纸量后再领料'},
                                status=400)

            received = (PaperTransaction.objects
                        .filter(order=order, paper=paper,
                                tx_type=PaperTransaction.TxType.OUT)
                        .aggregate(s=Sum('quantity'))['s'] or 0)
            remaining = order.paper_consumption - received
            if remaining <= 0:
                return Response(
                    {'detail': f'该订单用纸量 {order.paper_consumption} 张已全部领完'
                               f'（已领 {received} 张），请勿重复领料'},
                    status=400)

            raw = request.data.get('quantity')
            if raw in (None, ''):
                qty = remaining  # 默认一次领完全部未领
            else:
                try:
                    qty = int(raw)
                except (TypeError, ValueError):
                    return Response({'detail': '领料数量必须为整数'}, status=400)
            if qty <= 0:
                return Response({'detail': '领料数量必须大于 0'}, status=400)
            if qty > remaining:
                return Response(
                    {'detail': f'超出未领数量：用纸量 {order.paper_consumption} 张，'
                               f'已领 {received} 张，未领 {remaining} 张，'
                               f'本次最多可领 {remaining} 张'},
                    status=400)
            stock = int(paper.stock)
            if qty > stock:
                return Response(
                    {'detail': f'库存不足：当前库存 {stock} 张，'
                               f'本次需领 {qty} 张，还差 {qty - stock} 张'},
                    status=400)

            # 条件原子扣减：与纸张页出库同一口径，并发领料不会少扣
            updated = (Paper.objects.filter(pk=paper.pk, stock__gte=qty)
                       .update(stock=F('stock') - qty))
            if not updated:
                current = int((Paper.objects.filter(pk=paper.pk)
                               .values_list('stock', flat=True).first()))
                return Response(
                    {'detail': f'库存不足：当前库存 {current} 张，'
                               f'本次需领 {qty} 张，还差 {qty - current} 张'},
                    status=400)
            tx = PaperTransaction.objects.create(
                paper=paper, tx_type=PaperTransaction.TxType.OUT, quantity=qty,
                order=order, tx_date=today(),
                note=request.data.get('note') or f'{order.order_no} 生产领料',
            )

        data = OrderSerializer(self.get_object(), context={'request': request}).data
        data['receive_message'] = f'领料成功：{order.order_no} 本次出库 {tx.quantity} 张'
        return Response(data)


class ScheduleViewSet(viewsets.ModelViewSet):
    queryset = Schedule.objects.select_related('order', 'machine').all()
    serializer_class = ScheduleSerializer

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        date = request.query_params.get('date')
        machine_id = request.query_params.get('machine')
        if date:
            qs = qs.filter(planned_date=date)
        if machine_id:
            qs = qs.filter(machine_id=machine_id)
        return Response(self.get_serializer(qs, many=True).data)

    def perform_create(self, serializer):
        serializer.save()
        self._sync_machine_status()

    def perform_update(self, serializer):
        serializer.save()
        self._sync_machine_status()

    def perform_destroy(self, instance):
        machine_id = instance.machine_id
        instance.delete()
        # 删除排产后，受影响机台若已无未完成任务，回退为空闲
        self._sync_machine_status(machine_id)

    def _sync_machine_status(self, only_machine_id=None):
        cur = today()
        qs = Machine.objects.all()
        if only_machine_id:
            qs = qs.filter(pk=only_machine_id)
        for machine in qs:
            has_pending = machine.schedules.filter(planned_date__lte=cur, done=False).exists()
            if machine.status != Machine.Status.MAINTENANCE:
                machine.status = Machine.Status.RUNNING if has_pending else Machine.Status.IDLE
                machine.save(update_fields=['status'])


class ReworkViewSet(viewsets.ModelViewSet):
    queryset = ReworkRecord.objects.select_related('order').all()
    serializer_class = ReworkSerializer

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        status = request.query_params.get('status')
        if status:
            qs = qs.filter(status=status)
        return Response(self.get_serializer(qs, many=True).data)

    def perform_create(self, serializer):
        """新建返工单：订单与对应工序进入返工状态"""
        instance = serializer.save()
        progress = instance.order.progress
        field = {
            'prepress': 'prepress_status',
            'printing': 'printing_status',
            'binding': 'binding_status',
        }[instance.stage]
        if getattr(progress, field) != ProcessProgress.State.REWORK:
            setattr(progress, field, ProcessProgress.State.REWORK)
            progress.save(update_fields=[field])
        progress.sync_order_status()


class PaperTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PaperTransaction.objects.select_related('paper', 'order').all()
    serializer_class = PaperTransactionSerializer
    pagination_class = None


class DashboardViewSet(viewsets.ViewSet):
    """看板统计数据"""

    def list(self, request):
        cur = today()
        orders = Order.objects.select_related('customer', 'paper', 'progress').all()

        status_counts = {c[0]: 0 for c in Order.Status.choices}
        overdue, urgent, warning = [], [], []
        for o in orders:
            status_counts[o.status] = status_counts.get(o.status, 0) + 1
            if o.status == Order.Status.COMPLETED:
                continue
            days = (o.due_date - cur).days
            row = {
                'id': o.id, 'order_no': o.order_no,
                'product_name': o.product_name,
                'customer_name': o.customer.name,
                'status': o.status, 'status_display': o.get_status_display(),
                'due_date': o.due_date, 'days_left': days,
            }
            if days < 0:
                overdue.append(row)
            elif days <= 2:
                urgent.append(row)
            elif days <= 5:
                warning.append(row)

        low_papers = [
            {'id': p.id, 'name': p.name, 'spec': p.spec,
             'paper_type_display': p.get_paper_type_display(),
             'stock': p.stock, 'safety_stock': p.safety_stock}
            for p in Paper.objects.all() if p.is_low
        ]

        open_reworks = ReworkRecord.objects.exclude(status=ReworkRecord.Status.CLOSED).count()
        machines = Machine.objects.all()
        running = machines.filter(status=Machine.Status.RUNNING).count()

        # 近 7 日排产负荷（计划产量）
        from datetime import timedelta
        load = []
        for i in range(6, -1, -1):
            d = cur - timedelta(days=i)
            total = (Schedule.objects.filter(planned_date=d)
                     .aggregate(s=Sum('planned_qty'))['s'] or 0)
            load.append({'date': d.strftime('%m-%d'), 'planned_qty': total})

        # 各工序在制订单数
        stage_stats = {
            'prepress': orders.filter(progress__prepress_status__in=['in_progress', 'rework']).count(),
            'printing': orders.filter(progress__printing_status__in=['in_progress', 'rework']).count(),
            'binding': orders.filter(progress__binding_status__in=['in_progress', 'rework']).count(),
        }

        return Response({
            'summary': {
                'total_orders': orders.count(),
                'active_orders': orders.exclude(status=Order.Status.COMPLETED).count(),
                'completed_orders': status_counts.get('completed', 0),
                'overdue_count': len(overdue),
                'urgent_count': len(urgent),
                'warning_count': len(warning),
                'low_paper_count': len(low_papers),
                'open_rework_count': open_reworks,
                'machine_total': machines.count(),
                'machine_running': running,
            },
            'status_counts': status_counts,
            'overdue_orders': sorted(overdue, key=lambda x: x['days_left'])[:10],
            'urgent_orders': sorted(urgent, key=lambda x: x['days_left'])[:10],
            'warning_orders': warning[:10],
            'low_papers': low_papers,
            'stage_stats': stage_stats,
            'weekly_load': load,
        })

from django.db import transaction
from django.db.models import Count, Sum
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
    def stock_in(self, request, pk=None):
        """入库：增加库存并写流水"""
        paper = self.get_object()
        qty = self._parse_qty(request)
        if qty <= 0:
            return Response({'detail': '入库数量必须大于 0'}, status=400)
        with transaction.atomic():
            paper.stock += qty
            paper.save(update_fields=['stock'])
            PaperTransaction.objects.create(
                paper=paper, tx_type=PaperTransaction.TxType.IN, quantity=qty,
                tx_date=today(), note=request.data.get('note') or '采购入库',
            )
        return Response(PaperSerializer(paper).data)

    @action(detail=True, methods=['post'])
    def stock_out(self, request, pk=None):
        """出库（领料）：扣减库存并写流水"""
        paper = self.get_object()
        qty = self._parse_qty(request)
        if qty <= 0:
            return Response({'detail': '出库数量必须大于 0'}, status=400)
        if qty > paper.stock:
            return Response({'detail': f'库存不足，当前库存 {paper.stock} 张'}, status=400)
        order = None
        order_id = request.data.get('order')
        if order_id:
            order = Order.objects.filter(pk=order_id).first()
        with transaction.atomic():
            paper.stock -= qty
            paper.save(update_fields=['stock'])
            PaperTransaction.objects.create(
                paper=paper, tx_type=PaperTransaction.TxType.OUT, quantity=qty,
                order=order, tx_date=today(),
                note=request.data.get('note') or '生产领料',
            )
        return Response(PaperSerializer(paper).data)


class MachineViewSet(viewsets.ModelViewSet):
    queryset = Machine.objects.all().order_by('name')
    serializer_class = MachineSerializer


class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.select_related('customer', 'paper', 'progress').all()
    serializer_class = OrderSerializer

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

    def _sync_machine_status(self):
        cur = today()
        for machine in Machine.objects.all():
            has_today = machine.schedules.filter(planned_date__lte=cur, done=False).exists()
            if machine.status != Machine.Status.MAINTENANCE:
                machine.status = Machine.Status.RUNNING if has_today else Machine.Status.IDLE
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

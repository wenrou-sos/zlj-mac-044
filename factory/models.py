from datetime import date

from django.db import models
from django.utils import timezone

# 距保质期不足该天数视为“临期”
BATCH_WARNING_DAYS = 30


def today():
    """当前本地日期（兼容 USE_TZ=False）"""
    now = timezone.now()
    return timezone.localtime(now).date() if timezone.is_aware(now) else now.date()


class Customer(models.Model):
    name = models.CharField('客户名称', max_length=100, unique=True)
    contact = models.CharField('联系人', max_length=50, blank=True)
    phone = models.CharField('联系电话', max_length=30, blank=True)

    class Meta:
        verbose_name = '客户'
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.name


class Paper(models.Model):
    """纸张材料库存"""

    class PaperType(models.TextChoices):
        COATED = 'coated', '铜版纸'
        OFFSET = 'offset', '胶版纸'
        WHITEBOARD = 'whiteboard', '白卡纸'
        KRAFT = 'kraft', '牛皮纸'
        SPECIAL = 'special', '特种纸'

    name = models.CharField('纸张名称', max_length=100)
    paper_type = models.CharField('纸张类型', max_length=20, choices=PaperType.choices)
    spec = models.CharField('规格(克重/尺寸)', max_length=80, blank=True)
    stock = models.DecimalField('库存(张)', max_digits=12, decimal_places=0, default=0)
    safety_stock = models.DecimalField('安全库存(张)', max_digits=12, decimal_places=0, default=0)
    unit_price = models.DecimalField('单价(元/张)', max_digits=10, decimal_places=4, default=0)

    class Meta:
        verbose_name = '纸张材料'
        verbose_name_plural = verbose_name
        unique_together = ('name', 'spec')

    def __str__(self):
        return f'{self.name} {self.spec}'

    @property
    def is_low(self):
        return self.stock <= self.safety_stock


class PaperBatch(models.Model):
    """纸张批次：每批到货登记批次号、到货日期与保质期"""

    paper = models.ForeignKey(Paper, verbose_name='纸张', on_delete=models.CASCADE, related_name='batches')
    batch_no = models.CharField('批次号', max_length=50)
    arrival_date = models.DateField('到货日期', default=today)
    expiry_date = models.DateField('保质期至', null=True, blank=True)
    note = models.CharField('备注', max_length=200, blank=True)

    class Meta:
        verbose_name = '纸张批次'
        verbose_name_plural = verbose_name
        unique_together = ('paper', 'batch_no')
        ordering = ['arrival_date', 'id']

    def __str__(self):
        return f'{self.paper} [{self.batch_no}]'

    @property
    def remaining(self):
        """该批次当前剩余张数 = 入库合计 - 出库合计

        查询集若已 prefetch_related('transactions')，则直接在内存中汇总，避免 N+1 聚合。
        """
        cache = getattr(self, '_prefetched_objects_cache', {})
        if 'transactions' in cache:
            txs = cache['transactions']
            return sum(t.quantity if t.tx_type == PaperTransaction.TxType.IN else -t.quantity
                       for t in txs)
        agg = self.transactions.aggregate(
            in_qty=models.Sum('quantity', filter=models.Q(tx_type=PaperTransaction.TxType.IN)),
            out_qty=models.Sum('quantity', filter=models.Q(tx_type=PaperTransaction.TxType.OUT)),
        )
        return (agg['in_qty'] or 0) - (agg['out_qty'] or 0)

    @property
    def days_to_expiry(self):
        """距保质期天数；未登记保质期返回 None"""
        if not self.expiry_date:
            return None
        return (self.expiry_date - today()).days

    @property
    def expiry_state(self):
        """效期状态：expired 已过期 / warning 临期 / normal 正常 / none 无保质期"""
        days = self.days_to_expiry
        if days is None:
            return 'none'
        if days < 0:
            return 'expired'
        if days <= BATCH_WARNING_DAYS:
            return 'warning'
        return 'normal'


class Machine(models.Model):
    """印刷机台"""

    class Status(models.TextChoices):
        RUNNING = 'running', '生产中'
        IDLE = 'idle', '空闲'
        MAINTENANCE = 'maintenance', '维保中'

    name = models.CharField('机台名称', max_length=50, unique=True)
    machine_type = models.CharField('机型', max_length=50)
    status = models.CharField('状态', max_length=20, choices=Status.choices, default=Status.IDLE)

    class Meta:
        verbose_name = '机台'
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.name


class Order(models.Model):
    """生产订单"""

    class Status(models.TextChoices):
        PENDING = 'pending', '待排产'
        PREPRESS = 'prepress', '印前中'
        PRINTING = 'printing', '印刷中'
        BINDING = 'binding', '装订中'
        COMPLETED = 'completed', '已完成'
        REWORK = 'rework', '返工中'

    order_no = models.CharField('订单编号', max_length=30, unique=True)
    customer = models.ForeignKey(Customer, verbose_name='客户', on_delete=models.PROTECT, related_name='orders')
    product_name = models.CharField('产品名称', max_length=150)
    quantity = models.PositiveIntegerField('印数(份)')
    paper = models.ForeignKey(Paper, verbose_name='用纸', on_delete=models.PROTECT, related_name='orders')
    paper_consumption = models.PositiveIntegerField('用纸量(张)', default=0)
    status = models.CharField('订单状态', max_length=20, choices=Status.choices, default=Status.PENDING)
    order_date = models.DateField('下单日期')
    due_date = models.DateField('交货日期')
    completed_date = models.DateField('完工日期', null=True, blank=True)
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '订单'
        verbose_name_plural = verbose_name
        ordering = ['-order_date', '-id']

    def __str__(self):
        return f'{self.order_no} {self.product_name}'


class ProcessProgress(models.Model):
    """工序进度：印前 / 印刷 / 装订"""

    class Stage(models.TextChoices):
        PREPRESS = 'prepress', '印前'
        PRINTING = 'printing', '印刷'
        BINDING = 'binding', '装订'

    class State(models.TextChoices):
        NOT_STARTED = 'not_started', '未开始'
        IN_PROGRESS = 'in_progress', '进行中'
        DONE = 'done', '已完成'
        REWORK = 'rework', '返工中'

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='progress')
    prepress_status = models.CharField('印前状态', max_length=20, choices=State.choices, default=State.NOT_STARTED)
    prepress_progress = models.PositiveSmallIntegerField('印前进度%', default=0)
    prepress_note = models.CharField('印前说明', max_length=200, blank=True)
    prepress_finished_at = models.DateTimeField('印前完成时间', null=True, blank=True)

    printing_status = models.CharField('印刷状态', max_length=20, choices=State.choices, default=State.NOT_STARTED)
    printing_progress = models.PositiveSmallIntegerField('印刷进度%', default=0)
    printing_note = models.CharField('印刷说明', max_length=200, blank=True)
    printing_finished_at = models.DateTimeField('印刷完成时间', null=True, blank=True)

    binding_status = models.CharField('装订状态', max_length=20, choices=State.choices, default=State.NOT_STARTED)
    binding_progress = models.PositiveSmallIntegerField('装订进度%', default=0)
    binding_note = models.CharField('装订说明', max_length=200, blank=True)
    binding_finished_at = models.DateTimeField('装订完成时间', null=True, blank=True)

    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '工序进度'
        verbose_name_plural = verbose_name

    STAGE_FIELDS = {
        Stage.PREPRESS: ('prepress_status', 'prepress_progress', 'prepress_note', 'prepress_finished_at'),
        Stage.PRINTING: ('printing_status', 'printing_progress', 'printing_note', 'printing_finished_at'),
        Stage.BINDING: ('binding_status', 'binding_progress', 'binding_note', 'binding_finished_at'),
    }

    def stage_state(self, stage):
        return getattr(self, self.STAGE_FIELDS[stage][0])

    def sync_order_status(self):
        """根据三道工序状态与返工单，重新计算订单状态"""
        from django.utils import timezone

        order = self.order
        stages = [self.prepress_status, self.printing_status, self.binding_status]
        open_rework = order.reworks.exclude(status=ReworkRecord.Status.CLOSED).exists()

        if open_rework or 'rework' in stages:
            new_status = Order.Status.REWORK
        elif self.prepress_status == 'done' and self.printing_status == 'done' \
                and self.binding_status == 'done':
            # 必须三道工序全部完成才算完工
            new_status = Order.Status.COMPLETED
        elif self.binding_status in ('in_progress', 'done'):
            new_status = Order.Status.BINDING
        elif self.printing_status in ('in_progress', 'done'):
            new_status = Order.Status.PRINTING
        elif self.prepress_status in ('in_progress', 'done'):
            new_status = Order.Status.PREPRESS
        else:
            new_status = Order.Status.PENDING

        order.status = new_status
        if new_status == Order.Status.COMPLETED:
            order.completed_date = order.completed_date or today()
        else:
            order.completed_date = None
        order.save(update_fields=['status', 'completed_date'])
        return new_status


class Schedule(models.Model):
    """机台排产计划"""

    order = models.ForeignKey(Order, verbose_name='订单', on_delete=models.CASCADE, related_name='schedules')
    machine = models.ForeignKey(Machine, verbose_name='机台', on_delete=models.PROTECT, related_name='schedules')
    planned_date = models.DateField('计划日期')
    shift = models.CharField('班次', max_length=10, default='白班')
    planned_qty = models.PositiveIntegerField('计划产量(份)', default=0)
    actual_qty = models.PositiveIntegerField('实际产量(份)', default=0)
    done = models.BooleanField('是否完成', default=False)
    remark = models.CharField('备注', max_length=200, blank=True)

    class Meta:
        verbose_name = '排产计划'
        verbose_name_plural = verbose_name
        ordering = ['planned_date', 'shift', 'id']

    def __str__(self):
        return f'{self.planned_date} {self.machine} - {self.order.order_no}'


class ReworkRecord(models.Model):
    """返工跟踪单"""

    class Reason(models.TextChoices):
        COLOR = 'color', '色差'
        REGISTER = 'register', '套印不准'
        SCRATCH = 'scratch', '划伤/脏点'
        BINDING = 'binding', '装订错误'
        MATERIAL = 'material', '材料问题'
        OTHER = 'other', '其他'

    class Status(models.TextChoices):
        OPEN = 'open', '待处理'
        PROCESSING = 'processing', '返工中'
        CLOSED = 'closed', '已闭环'

    order = models.ForeignKey(Order, verbose_name='订单', on_delete=models.CASCADE, related_name='reworks')
    stage = models.CharField('返工工序', max_length=20, choices=ProcessProgress.Stage.choices)
    reason = models.CharField('返工原因', max_length=20, choices=Reason.choices)
    qty = models.PositiveIntegerField('返工数量(份)', default=0)
    status = models.CharField('处理状态', max_length=20, choices=Status.choices, default=Status.OPEN)
    description = models.TextField('问题描述', blank=True)
    handler = models.CharField('责任人', max_length=50, blank=True)
    found_at = models.DateField('发现日期')
    closed_at = models.DateField('闭环日期', null=True, blank=True)
    result = models.TextField('处理结果', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '返工单'
        verbose_name_plural = verbose_name
        ordering = ['-found_at', '-id']

    def __str__(self):
        return f'返工单 {self.id} - {self.order.order_no}'


class PaperTransaction(models.Model):
    """纸张出入库流水"""

    class TxType(models.TextChoices):
        IN = 'in', '入库'
        OUT = 'out', '出库'

    paper = models.ForeignKey(Paper, verbose_name='纸张', on_delete=models.CASCADE, related_name='transactions')
    batch = models.ForeignKey(PaperBatch, verbose_name='批次', on_delete=models.SET_NULL,
                              null=True, blank=True, related_name='transactions')
    tx_type = models.CharField('类型', max_length=10, choices=TxType.choices)
    quantity = models.PositiveIntegerField('数量(张)')
    order = models.ForeignKey(Order, verbose_name='关联订单', on_delete=models.SET_NULL, null=True, blank=True)
    tx_date = models.DateField('日期')
    note = models.CharField('备注', max_length=200, blank=True)

    class Meta:
        verbose_name = '纸张流水'
        verbose_name_plural = verbose_name
        ordering = ['-tx_date', '-id']

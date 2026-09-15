from rest_framework import serializers

from .models import (
    today as _today,
    Customer,
    Machine,
    Order,
    Paper,
    PaperTransaction,
    ProcessProgress,
    ReworkRecord,
    Schedule,
)


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = '__all__'


class PaperSerializer(serializers.ModelSerializer):
    paper_type_display = serializers.CharField(source='get_paper_type_display', read_only=True)
    is_low = serializers.BooleanField(read_only=True)

    class Meta:
        model = Paper
        fields = '__all__'


class MachineSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Machine
        fields = '__all__'


class ProcessProgressSerializer(serializers.ModelSerializer):
    prepress_status_display = serializers.CharField(source='get_prepress_status_display', read_only=True)
    printing_status_display = serializers.CharField(source='get_printing_status_display', read_only=True)
    binding_status_display = serializers.CharField(source='get_binding_status_display', read_only=True)

    order_quantity = serializers.IntegerField(source='order.quantity', read_only=True)
    prepress_rework_qty = serializers.SerializerMethodField()
    printing_rework_qty = serializers.SerializerMethodField()
    binding_rework_qty = serializers.SerializerMethodField()
    prepress_waste_qty = serializers.SerializerMethodField()
    printing_waste_qty = serializers.SerializerMethodField()
    binding_waste_qty = serializers.SerializerMethodField()

    class Meta:
        model = ProcessProgress
        fields = '__all__'
        read_only_fields = ['order', 'updated_at']

    # stage -> (状态, 进度%, 实际产量, 合格数, 说明)
    STAGE_ATTRS = {
        'prepress': ('prepress_status', 'prepress_progress', 'prepress_actual_qty',
                     'prepress_qualified_qty', 'prepress_note'),
        'printing': ('printing_status', 'printing_progress', 'printing_actual_qty',
                     'printing_qualified_qty', 'printing_note'),
        'binding': ('binding_status', 'binding_progress', 'binding_actual_qty',
                    'binding_qualified_qty', 'binding_note'),
    }

    def _rework_map(self, obj):
        if not hasattr(self, '_rework_cache') or self._rework_cache[0] != obj.id:
            totals = {'prepress': 0, 'printing': 0, 'binding': 0}
            for stage, qty in obj.order.reworks.values_list('stage', 'qty'):
                totals[stage] = totals.get(stage, 0) + qty
            self._rework_cache = (obj.id, totals)
        return self._rework_cache[1]

    def get_prepress_rework_qty(self, obj):
        return self._rework_map(obj)['prepress']

    def get_printing_rework_qty(self, obj):
        return self._rework_map(obj)['printing']

    def get_binding_rework_qty(self, obj):
        return self._rework_map(obj)['binding']

    def _waste(self, obj, stage):
        fields = self.STAGE_ATTRS[stage]
        rework = self._rework_map(obj)[stage]
        return getattr(obj, fields[2]) - getattr(obj, fields[3]) + rework

    def get_prepress_waste_qty(self, obj):
        return self._waste(obj, 'prepress')

    def get_printing_waste_qty(self, obj):
        return self._waste(obj, 'printing')

    def get_binding_waste_qty(self, obj):
        return self._waste(obj, 'binding')

    def validate(self, attrs):
        # 合并实例当前值，使部分更新(PATCH)也能做整体顺序校验
        merged = {}
        for stage, (s_field, p_field, a_field, q_field, _) in self.STAGE_ATTRS.items():
            merged[s_field] = attrs.get(s_field, getattr(self.instance, s_field, None))
            merged[p_field] = attrs.get(p_field, getattr(self.instance, p_field, None))
            merged[a_field] = attrs.get(a_field, getattr(self.instance, a_field, None))
            merged[q_field] = attrs.get(q_field, getattr(self.instance, q_field, None))

        # 校验进度值 0-100，状态与进度一致性
        for stage, (s_field, p_field, a_field, q_field, _) in self.STAGE_ATTRS.items():
            status = attrs.get(s_field)
            progress = attrs.get(p_field)
            actual = attrs.get(a_field)
            qualified = attrs.get(q_field)
            if progress is not None and not 0 <= progress <= 100:
                raise serializers.ValidationError({p_field: '进度必须在 0~100 之间'})
            if status == 'done' and progress is not None and progress < 100:
                raise serializers.ValidationError({p_field: '状态为已完成时进度应为 100%'})
            if status == 'not_started' and progress is not None and progress > 0:
                raise serializers.ValidationError({p_field: '状态为未开始时进度应为 0%'})
            # 合格数不能大于实际产量（只提交其一时与库内现值比较）
            if qualified is not None:
                eff_actual = actual if actual is not None else getattr(self.instance, a_field, 0)
                if qualified > eff_actual:
                    raise serializers.ValidationError(
                        {q_field: '合格数不能大于实际产量'})
            # 未开始的工序不能登记正产量
            eff_status = status if status is not None else getattr(self.instance, s_field)
            if eff_status == 'not_started' and actual is not None and actual > 0:
                raise serializers.ValidationError(
                    {a_field: '工序尚未开始，不能登记产量'})

        # 工序顺序校验：印刷完成前印前必须完成；装订完成前印前、印刷必须完成
        if merged['printing_status'] == 'done' and merged['prepress_status'] != 'done':
            raise serializers.ValidationError(
                {'printing_status': '印前工序尚未完成，不能将印刷标记为已完成'})
        if merged['binding_status'] == 'done':
            unfinished = []
            if merged['prepress_status'] != 'done':
                unfinished.append('印前')
            if merged['printing_status'] != 'done':
                unfinished.append('印刷')
            if unfinished:
                raise serializers.ValidationError(
                    {'binding_status': f'{"、".join(unfinished)}尚未完成，不能将装订标记为已完成'})
        return attrs

    def update(self, instance, validated_data):
        from django.utils import timezone

        # 工序由未开始转为开工、且未显式登记产量时，实际产量/合格数默认取订单印数
        order_qty = instance.order.quantity
        for stage, (s_field, p_field, a_field, q_field, _) in self.STAGE_ATTRS.items():
            new_status = validated_data.get(s_field)
            if (new_status and new_status != 'not_started'
                    and getattr(instance, s_field) == 'not_started'
                    and a_field not in validated_data
                    and q_field not in validated_data
                    and getattr(instance, a_field) == 0):
                validated_data[a_field] = order_qty
                validated_data[q_field] = order_qty

        instance = super().update(instance, validated_data)

        # 状态回到未开始时清空产量
        reset_fields = []
        for stage, (s_field, p_field, a_field, q_field, _) in self.STAGE_ATTRS.items():
            if getattr(instance, s_field) == 'not_started' \
                    and (getattr(instance, a_field) or getattr(instance, q_field)):
                setattr(instance, a_field, 0)
                setattr(instance, q_field, 0)
                reset_fields += [a_field, q_field]

        # 完成某工序时记录完成时间；重新打开则清空
        finished_map = {
            'prepress': 'prepress_finished_at',
            'printing': 'printing_finished_at',
            'binding': 'binding_finished_at',
        }
        status_map = {
            'prepress': 'prepress_status',
            'printing': 'printing_status',
            'binding': 'binding_status',
        }
        for stage, ts_field in finished_map.items():
            if getattr(instance, status_map[stage]) == 'done' and not getattr(instance, ts_field):
                setattr(instance, ts_field, timezone.now())
                reset_fields.append(ts_field)
            elif getattr(instance, status_map[stage]) != 'done' and getattr(instance, ts_field):
                setattr(instance, ts_field, None)
                reset_fields.append(ts_field)
        instance.save(update_fields=reset_fields or None)
        instance.sync_order_status()
        return instance


class OrderListSerializer(serializers.ModelSerializer):
    """列表精简结构（含看板需要的派生字段）"""

    customer_name = serializers.CharField(source='customer.name', read_only=True)
    paper_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    days_left = serializers.SerializerMethodField()
    warning_level = serializers.SerializerMethodField()
    progress = ProcessProgressSerializer(read_only=True)
    open_rework_count = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'order_no', 'customer', 'customer_name', 'product_name',
            'quantity', 'paper', 'paper_name', 'paper_consumption',
            'status', 'status_display', 'order_date', 'due_date',
            'completed_date', 'remark', 'days_left', 'warning_level',
            'progress', 'open_rework_count',
        ]

    def get_paper_name(self, obj):
        return f'{obj.paper.name} {obj.paper.spec}'

    def get_days_left(self, obj):
        cur = _today()
        if obj.status == Order.Status.COMPLETED:
            return None
        return (obj.due_date - cur).days

    def get_warning_level(self, obj):
        """交期预警：overdue 逾期 / urgent 紧急(<=2天) / warning 预警(<=5天) / normal"""
        days = self.get_days_left(obj)
        if days is None:
            return 'completed'
        if days < 0:
            return 'overdue'
        if days <= 2:
            return 'urgent'
        if days <= 5:
            return 'warning'
        return 'normal'

    def get_open_rework_count(self, obj):
        return obj.reworks.exclude(status=ReworkRecord.Status.CLOSED).count()


class OrderSerializer(OrderListSerializer):
    schedules = serializers.SerializerMethodField()
    reworks = serializers.SerializerMethodField()

    class Meta(OrderListSerializer.Meta):
        fields = OrderListSerializer.Meta.fields + ['created_at', 'schedules', 'reworks']

    def get_schedules(self, obj):
        return ScheduleSerializer(obj.schedules.select_related('machine'), many=True).data

    def get_reworks(self, obj):
        return ReworkSerializer(obj.reworks.all(), many=True).data


class ScheduleSerializer(serializers.ModelSerializer):
    order_no = serializers.CharField(source='order.order_no', read_only=True)
    product_name = serializers.CharField(source='order.product_name', read_only=True)
    machine_name = serializers.CharField(source='machine.name', read_only=True)

    class Meta:
        model = Schedule
        fields = '__all__'


class ReworkSerializer(serializers.ModelSerializer):
    order_no = serializers.CharField(source='order.order_no', read_only=True)
    product_name = serializers.CharField(source='order.product_name', read_only=True)
    stage_display = serializers.CharField(source='get_stage_display', read_only=True)
    reason_display = serializers.CharField(source='get_reason_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = ReworkRecord
        fields = '__all__'

    def update(self, instance, validated_data):
        from django.utils import timezone
        instance = super().update(instance, validated_data)

        order = instance.order
        open_exists = order.reworks.exclude(status=ReworkRecord.Status.CLOSED).exists()
        progress = order.progress

        if instance.status == 'closed':
            instance.closed_at = instance.closed_at or _today()
            instance.save(update_fields=['closed_at'])
            # 该订单已无未闭环返工单时，把仍标记返工的工序恢复为进行中
            stage_status_field = {
                'prepress': 'prepress_status',
                'printing': 'printing_status',
                'binding': 'binding_status',
            }[instance.stage]
            if not open_exists:
                changed = []
                for _, f in [('prepress', 'prepress_status'),
                             ('printing', 'printing_status'),
                             ('binding', 'binding_status')]:
                    if getattr(progress, f) == ProcessProgress.State.REWORK:
                        setattr(progress, f, ProcessProgress.State.IN_PROGRESS)
                        changed.append(f)
                if changed:
                    progress.save(update_fields=changed)
            progress.sync_order_status()
        elif instance.status == 'processing':
            stage_status_field = {
                'prepress': 'prepress_status',
                'printing': 'printing_status',
                'binding': 'binding_status',
            }[instance.stage]
            if getattr(progress, stage_status_field) != ProcessProgress.State.REWORK:
                setattr(progress, stage_status_field, ProcessProgress.State.REWORK)
                progress.save(update_fields=[stage_status_field])
            progress.sync_order_status()
        return instance


class PaperTransactionSerializer(serializers.ModelSerializer):
    paper_name = serializers.CharField(source='paper.name', read_only=True)
    tx_type_display = serializers.CharField(source='get_tx_type_display', read_only=True)
    order_no = serializers.CharField(source='order.order_no', read_only=True, allow_null=True)

    class Meta:
        model = PaperTransaction
        fields = '__all__'

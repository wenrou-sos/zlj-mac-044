from django.contrib import admin

from .models import (
    Customer,
    Machine,
    MachineShiftCapacity,
    Order,
    Paper,
    PaperTransaction,
    ProcessProgress,
    ReworkRecord,
    Schedule,
)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact', 'phone')
    search_fields = ('name',)


@admin.register(Paper)
class PaperAdmin(admin.ModelAdmin):
    list_display = ('name', 'paper_type', 'spec', 'stock', 'safety_stock', 'unit_price')
    list_filter = ('paper_type',)
    search_fields = ('name', 'spec')


class MachineShiftCapacityInline(admin.TabularInline):
    model = MachineShiftCapacity
    extra = 2


@admin.register(Machine)
class MachineAdmin(admin.ModelAdmin):
    list_display = ('name', 'machine_type', 'status', 'capacity_summary')
    list_filter = ('status',)
    inlines = [MachineShiftCapacityInline]

    @admin.display(description='班次产能(白班/夜班)')
    def capacity_summary(self, obj):
        day = obj.shift_capacity('白班')
        night = obj.shift_capacity('夜班')
        fmt = lambda v: '未登记' if v is None else f'{v}份'
        return f'{fmt(day)} / {fmt(night)}'


class ProcessProgressInline(admin.StackedInline):
    model = ProcessProgress
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_no', 'customer', 'product_name', 'quantity', 'status', 'order_date', 'due_date')
    list_filter = ('status',)
    search_fields = ('order_no', 'product_name')
    inlines = [ProcessProgressInline]


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ('planned_date', 'shift', 'machine', 'order', 'planned_qty', 'actual_qty', 'done')
    list_filter = ('planned_date', 'machine', 'done')


@admin.register(ReworkRecord)
class ReworkRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'stage', 'reason', 'qty', 'status', 'found_at', 'closed_at')
    list_filter = ('status', 'stage', 'reason')


@admin.register(PaperTransaction)
class PaperTransactionAdmin(admin.ModelAdmin):
    list_display = ('tx_date', 'paper', 'tx_type', 'quantity', 'order')
    list_filter = ('tx_type', 'tx_date')

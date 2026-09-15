from django.contrib import admin

from .models import (
    Customer,
    Machine,
    Order,
    Paper,
    PaperBatch,
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


@admin.register(PaperBatch)
class PaperBatchAdmin(admin.ModelAdmin):
    list_display = ('batch_no', 'paper', 'remaining_display', 'arrival_date', 'expiry_date', 'note')
    list_filter = ('arrival_date', 'expiry_date')
    search_fields = ('batch_no', 'paper__name', 'paper__spec')
    autocomplete_fields = ('paper',)

    @admin.display(description='剩余张数')
    def remaining_display(self, obj):
        return obj.remaining


@admin.register(Machine)
class MachineAdmin(admin.ModelAdmin):
    list_display = ('name', 'machine_type', 'status')
    list_filter = ('status',)


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
    list_display = ('tx_date', 'paper', 'batch', 'tx_type', 'quantity', 'order')
    list_filter = ('tx_type', 'tx_date')
    autocomplete_fields = ('paper', 'batch')

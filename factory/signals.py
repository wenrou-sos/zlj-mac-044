from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Order, ProcessProgress, Shipment


@receiver(post_save, sender=Order)
def ensure_progress(sender, instance, created, **kwargs):
    """新建订单时自动创建工序进度记录"""
    if created and not hasattr(instance, 'progress'):
        ProcessProgress.objects.create(order=instance)


@receiver(post_save, sender=Shipment)
@receiver(post_delete, sender=Shipment)
def sync_order_on_shipment(sender, instance, **kwargs):
    """发货记录增删改后，联动订单的 待发货/已发货 状态"""
    instance.order.sync_shipment_status()

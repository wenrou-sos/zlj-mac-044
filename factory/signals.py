from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Order, ProcessProgress


@receiver(post_save, sender=Order)
def ensure_progress(sender, instance, created, **kwargs):
    """新建订单时自动创建工序进度记录"""
    if created and not hasattr(instance, 'progress'):
        ProcessProgress.objects.create(order=instance)

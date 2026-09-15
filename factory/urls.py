from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CustomerViewSet,
    DashboardViewSet,
    MachineViewSet,
    OrderViewSet,
    PaperTransactionViewSet,
    PaperViewSet,
    ReworkViewSet,
    ScheduleViewSet,
    ShipmentViewSet,
)

router = DefaultRouter()
router.register('customers', CustomerViewSet, basename='customer')
router.register('papers', PaperViewSet, basename='paper')
router.register('machines', MachineViewSet, basename='machine')
router.register('orders', OrderViewSet, basename='order')
router.register('schedules', ScheduleViewSet, basename='schedule')
router.register('reworks', ReworkViewSet, basename='rework')
router.register('shipments', ShipmentViewSet, basename='shipment')
router.register('paper-transactions', PaperTransactionViewSet, basename='papertransaction')
router.register('dashboard', DashboardViewSet, basename='dashboard')

urlpatterns = [
    path('', include(router.urls)),
]

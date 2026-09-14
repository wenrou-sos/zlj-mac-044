from django.apps import AppConfig


class FactoryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'factory'
    verbose_name = '印刷厂生产管理'

    def ready(self):
        from . import signals  # noqa: F401

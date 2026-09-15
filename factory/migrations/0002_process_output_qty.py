from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('factory', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='processprogress',
            name='prepress_actual_qty',
            field=models.PositiveIntegerField(default=0, verbose_name='印前实际产量(份)'),
        ),
        migrations.AddField(
            model_name='processprogress',
            name='prepress_qualified_qty',
            field=models.PositiveIntegerField(default=0, verbose_name='印前合格数(份)'),
        ),
        migrations.AddField(
            model_name='processprogress',
            name='printing_actual_qty',
            field=models.PositiveIntegerField(default=0, verbose_name='印刷实际产量(份)'),
        ),
        migrations.AddField(
            model_name='processprogress',
            name='printing_qualified_qty',
            field=models.PositiveIntegerField(default=0, verbose_name='印刷合格数(份)'),
        ),
        migrations.AddField(
            model_name='processprogress',
            name='binding_actual_qty',
            field=models.PositiveIntegerField(default=0, verbose_name='装订实际产量(份)'),
        ),
        migrations.AddField(
            model_name='processprogress',
            name='binding_qualified_qty',
            field=models.PositiveIntegerField(default=0, verbose_name='装订合格数(份)'),
        ),
    ]

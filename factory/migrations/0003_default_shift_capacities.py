from django.db import migrations


def fill_default_capacities(apps, schema_editor):
    """给已存在但未登记班次产能的机台补默认产能（白班/夜班各 10000 份）"""
    Machine = apps.get_model('factory', 'Machine')
    MachineShiftCapacity = apps.get_model('factory', 'MachineShiftCapacity')
    for machine in Machine.objects.all():
        for shift in ('白班', '夜班'):
            MachineShiftCapacity.objects.get_or_create(
                machine=machine, shift=shift, defaults={'capacity': 10000})


def remove_capacities(apps, schema_editor):
    MachineShiftCapacity = apps.get_model('factory', 'MachineShiftCapacity')
    MachineShiftCapacity.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('factory', '0002_alter_schedule_shift_machineshiftcapacity'),
    ]

    operations = [
        migrations.RunPython(fill_default_capacities, remove_capacities),
    ]

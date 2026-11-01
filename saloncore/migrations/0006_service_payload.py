from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('saloncore', '0005_service_external_id_service_uniq_service_external_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='service',
            name='payload',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]

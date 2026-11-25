from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("analyses", "0002_action_labels_from_catalog")]

    operations = [
        migrations.AddField(
            model_name="personprediction",
            name="valid_feature_ratio",
            field=models.FloatField(blank=True, null=True, verbose_name="관절 검출률"),
        ),
    ]

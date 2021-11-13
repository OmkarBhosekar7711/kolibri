# -*- coding: utf-8 -*-
# Generated by Django 1.11.29 on 2021-11-04 16:08
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        ("logger", "0009_null_channel_id_unconstrained_mastery_level"),
    ]

    operations = [
        migrations.AlterField(
            model_name="attemptlog",
            name="item",
            field=models.CharField(
                max_length=200,
                validators=[django.core.validators.MinLengthValidator(1)],
            ),
        ),
        migrations.AlterField(
            model_name="contentsessionlog",
            name="kind",
            field=models.CharField(
                max_length=200,
                validators=[django.core.validators.MinLengthValidator(1)],
            ),
        ),
        migrations.AlterField(
            model_name="contentsummarylog",
            name="kind",
            field=models.CharField(
                max_length=200,
                validators=[django.core.validators.MinLengthValidator(1)],
            ),
        ),
        migrations.AlterField(
            model_name="examattemptlog",
            name="item",
            field=models.CharField(
                max_length=200,
                validators=[django.core.validators.MinLengthValidator(1)],
            ),
        ),
    ]

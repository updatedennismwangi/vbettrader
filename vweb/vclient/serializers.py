from abc import ABC

from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import serializers


class RegisterSerializer(serializers.Serializer):
    username = serializers.EmailField(min_length=2, max_length=50)
    password = serializers.CharField(min_length=2, max_length=50)


class LoginSerializer(serializers.Serializer):
    username = serializers.EmailField(min_length=2, max_length=50)
    password = serializers.CharField(min_length=2, max_length=50)


class AuthSerializer(serializers.Serializer):
    username = serializers.EmailField(min_length=2, max_length=50)
    pin = serializers.IntegerField()


class ForgotSerializer(serializers.Serializer):
    username = serializers.EmailField(min_length=2, max_length=50)

class ForgotResetSerializer(serializers.Serializer):
    username = serializers.CharField(min_length=1, max_length=50)
    token = serializers.CharField(min_length=32)


class ForgotResetConfirmSerializer(serializers.Serializer):
    username = serializers.CharField(min_length=1, max_length=50)
    token = serializers.CharField(min_length=32)
    password = serializers.CharField(min_length=2, max_length=32)

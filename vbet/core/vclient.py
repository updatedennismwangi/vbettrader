import os

import django
from django.conf import settings
from . import settings as app_settings

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEBUG = app_settings.DJANGO_DEBUG

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.admin',
    'django.contrib.auth',
    'vbet.core.vclient',
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': 'vweb',
        'USER': 'vweb',
        'PASSWORD': 'vbetserver',
        'HOST': 'localhost',
        'PORT': '',
        'CONN_MAX_AGE': None
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [("localhost", 6379)],
        },
    },
}

settings.configure(
    INSTALLED_APPS=INSTALLED_APPS,
    DATABASES=DATABASES,
    CHANNEL_LAYERS=CHANNEL_LAYERS
)

django.setup()

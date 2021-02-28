"""
ASGI config for vweb project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/3.1/howto/deployment/asgi/
"""

import os

# Fetch Django ASGI application early to ensure AppRegistry is populated
# before importing consumers and AuthMiddlewareStack that may import ORM
# models.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vweb.vweb.settings')

from django.conf.urls import url
from django.core.asgi import get_asgi_application
django_asgi_app = get_asgi_application()
# from .middleware import middleWareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.urls import path
from .session import WsSession


websocket = URLRouter([
    path('api/wss/', WsSession.as_asgi(), name="endpoint")
])

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': websocket
})


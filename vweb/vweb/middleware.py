from django.db import close_old_connections
from channels.db import database_sync_to_async
from channels.auth import AuthMiddlewareStack
from django.contrib.auth import get_user_model
from . import settings

import jwt


class WsAuthMiddleware:
    async_capable = False

    def __init__(self, inner):
        # Store the ASGI application we were passed
        self.inner = inner

    def __call__(self, scope):
        return WsAuthMiddlewareInstance(scope, self)


class WsAuthMiddlewareInstance:
    def __init__(self, scope, middleware):
        self.middleware = middleware
        self.scope = dict(scope)
        self.inner = self.middleware.inner

    async def __call__(self, receive, send):
        # Close old database connections to prevent usage of timed out connections
        close_old_connections()
        user = None
        if not self.scope.get('user', None):
            path = self.scope.get('path', None)
            if path:
                p = path.split('/')
                if len(p) == 3:
                    scheme, token = p[1], p[2]
                    if scheme == 'wss':
                        try:
                            payload = jwt.decode(token, settings.SECRET_KEY)
                        except jwt.exceptions.DecodeError:
                            msg = 'Invalid authentication. Could not decode token.'
                        else:
                            try:
                                user_id = payload.get('id', None)
                                token = payload.get('token', None)
                                user = await get_user(user_id)
                            except get_user_model().DoesNotExist:
                                msg = 'No user matching this token was found.'
        self.scope['user'] = user
        inner = self.inner(self.scope)
        return await inner(receive, send)


@database_sync_to_async
def get_user(user_id: int):
    return get_user_model().objects.get(id=user_id)


def middleWareStack(inner):
    return WsAuthMiddleware(inner)

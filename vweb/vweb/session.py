from __future__ import annotations

from typing import Optional, TYPE_CHECKING, List, Dict

from channels.generic.websocket import AsyncJsonWebsocketConsumer

from vweb.vweb import settings
from vweb.utils import decode_json, encode_json, parse_wss_payload

from asgiref.sync import async_to_sync
from .profile import Profile
import jwt
from django.db import close_old_connections
from channels.db import database_sync_to_async
from channels.auth import AuthMiddlewareStack
from django.contrib.auth import get_user_model
import aioredis
import logging
from vweb.vclient.models import Token

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from vweb.vclient.models import User

import asyncio
import secrets


SUDO_URI = {
    'exit': 'application',
    'add': 'manager',
    'login': 'manager',
    'check': 'manager'
}

CLIENT_URI = {'player': 'manager'}


redis: aioredis.ConnectionsPool = async_to_sync(aioredis.create_redis_pool)(settings.REDIS_URI, minsize=5, maxsize=30)


class WsSession(AsyncJsonWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.profiles: Dict[str, Profile] = {}

    async def connect(self):
        # This method runs for every websocket connection when it connects

        # For now nothing special just accept the connection
        await self.accept()

    async def receive_json(self, content, **kwargs):
        # This is run everytime we receive a message that is of json format which
        # is what we have by default
        uri, client_id, data = parse_wss_payload(content)
        # TODO: FILTER INVALID CMD COMMANDS
        if not isinstance(uri, str):
            return
        uri = uri.lower()
        # Filter uri to make sure its a supported command
        if uri not in ['init', 'provider_add', 'providers_enabled', 'tickets', 'create_session', 'sessions_stop',
                       'sessions_pause', 'sessions_mute']:
            logger.warning("Invalid Payload from wss : %s", str(content))
            await self.close(code=4008)
            return

        # If the user is already authenticated pass the message to the profile class of this
        # user for processing
        if client_id in self.profiles:
            profile = self.profiles.get(client_id)
            await profile.on_message(uri, data)
        # If user is not authenticated check if the uri is init and try to authenticate
        elif uri == 'init':
            # Check if user payload has a token
            token = data.get('token')
            if isinstance(token, str):
                try:
                    # Try to decode the token using app secret key
                    payload = jwt.decode(token, settings.SECRET_KEY)
                except jwt.exceptions.DecodeError:
                    msg = 'Invalid authentication. Could not decode token.'
                    logger.warning(msg + " : %s", token)
                else:
                    # If decode success then extract the two parameters : id, token
                    try:
                        user_id = payload.get('id', None)
                        token = payload.get('token', None)
                        # We try and identify the user from our database using his id
                        user = await get_user(user_id)
                    except get_user_model().DoesNotExist:
                        msg = 'No user matching this token was found.'
                        logger.warning(msg + " : %s", payload)
                    else:
                        # Check token status
                        try:
                            user.auth_token.get(token=token)
                        except Token.DoesNotExist:
                            logger.warning("Token does not exist : %s", token)
                            await self.close(4005)
                        else:
                            # If user identity is okay then create a profile for this person and process
                            # all messages with it
                            if user.activated:
                                logger.info("User online %r", user)
                                session_key: str = self.get_session_key()
                                profile = Profile(user, self, session_key, self.channel_name)
                                self.profiles.setdefault(session_key, profile)
                                await profile.on_message(uri, data)
                            else:
                                await self.close(4002)
        # Just ignore
        else:
            logger.warning("Invalid Payload from wss : %s", str(content))
            await self.close(code=4007)

    async def disconnect(self, close_code):
        # Runs when the websocket connection is disconnected so that we can clean resources.
        for profile in self.profiles.values():
            await profile.on_disconnect(close_code)

    async def chat_message(self, data):
        # Runs when the websocket connection receives a message from vbet-server
        uri = data.get('uri')
        session_key = data.get('session_key')
        body = decode_json(data.get('body'))
        provider = data.get('provider')
        profile = self.profiles.get(session_key)
        if uri == 'init':
            success = body.get('success')
            if success:
                body = body.get('body')
            profile.init_map[provider] = body
            for k, v in profile.init_map.items():
                if not v:
                    return
            if all(profile.init_map):
                message = {
                    'cmd': 'init',
                    'clientId': profile.client_id,
                    'body': {
                        'providers': {
                            'enabledProviders': profile.providers,
                            'installedProviders': await profile.get_installed_providers(),
                            'providers': profile.init_map
                        },
                        'settings': {
                        }
                    }
                }
                to_send = message
        elif uri in ['tickets', 'ticket', 'ticket_resolve']:
            message = {
                'cmd': uri,
                'body': {
                    provider: {
                        'tickets': body
                    }
                }
            }
            to_send = message
        elif uri == 'account_info':
            message = {
                'cmd': uri,
                'body': {
                    'providers': {
                        provider: body
                    }
                }
            }
            to_send = message
        elif uri == 'sessions_update':
            message = {
                'cmd': uri,
                'body': {
                    provider: {
                        'sessions': body
                    }
                }
            }
            to_send = message
        elif uri == 'create_session':
            message = {
                'cmd': uri,
                'body': {
                    provider: {**body}
                }
            }
            to_send = message
        elif uri == 'exit':
            to_send = {
                'cmd': uri,
                'body': {
                    provider: {**body}
                }
            }
        else:
            to_send = {'cmd': uri, 'body': body}

        # print(to_send)
        if to_send:
            await self.send_json(to_send)

    @staticmethod
    def get_session_key() -> str:
        return secrets.token_urlsafe(32)


@database_sync_to_async
def get_user(user_id: int):
    # Normal django get from db
    return get_user_model().objects.get(id=user_id)


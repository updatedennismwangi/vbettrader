import logging

from typing import Dict, List, Optional, Tuple, TYPE_CHECKING, Any
from channels.db import database_sync_to_async
from asgiref.sync import sync_to_async
from operator import itemgetter

logger = logging.getLogger(__name__)
import json
from vweb.vclient.models import User, Providers, ProviderInstalled
import asyncio
import aioredis
from vweb.utils import parse_wss_payload, parse_cmd_key, decode_json
from vweb.vweb import settings

if TYPE_CHECKING:
    from .session import WsSession


class Profile:
    def __init__(self, user: User, session, client_id: str, channel_name: str):
        self.user: User = user
        self.session = session  # type: WsSession
        self.client_id: str = client_id
        self.providers: Dict[str, Dict] = {}
        self.live_providers: Dict[str] = {}
        from .session import redis
        self.redis: aioredis.ConnectionsPool = redis
        self.channel_name: str = channel_name
        self.request_tasks: Dict[Tuple[int, str], asyncio.Future] = {}
        self.request_events: Dict[int, asyncio.Event] = {}
        self.message_id = 0
        self.init_map = {}
        self.provider_map: Dict[str, str] = {}

    async def on_message(self, uri: str, data: Dict):
        self.message_id += 1
        message_id = self.message_id
        # The callback is gotten from this class using a name called cmd_xxxxxx
        callback = getattr(self, f'cmd_{uri}', None)
        # Schedule the callback as a task and return
        future = asyncio.create_task(callback(data))
        # We add the message done callback so its run when this function completes
        # If the callback returns data, It is sent to the user
        future.add_done_callback(self.message_done)
        future.set_name(f'{uri}_{message_id}')
        self.request_tasks[(message_id, uri)] = future

    def message_done(self, future: asyncio.Task):
        cmd, message_id = parse_cmd_key(future.get_name())
        index = (int(message_id), cmd)
        callback = getattr(self, f'cmd_{cmd}_response', None)
        if callback:
            callback, cmd, future.result(), future.exception()
            callback(future.result(), future.exception())
            self.request_tasks.pop(index)

    async def cmd_init(self, data: Dict):
        # When the user sends an init message we first go through our database
        # to find all betting companies this user has registered with us (providers)
        self.providers = await self.get_user_providers()
        installed_providers = await self.get_installed_providers()
        message = {
            'cmd': 'init',
            'clientId': self.client_id,
            'body': {
                'providers': {
                    'enabledProviders': self.providers,
                    'installedProviders': installed_providers,
                    'providers': {}
                },
                'settings': {
                }
            }
        }
        if not self.providers:
            return message
            # If he has none we send basic login information needed by our app subject to change(where you come in)
        else:
            self.init_map = {}
            con: aioredis.Redis
            with await self.redis as con:
                tasks = {}
                for provider, provider_data in self.providers.items():
                    self.init_map[provider] = {}
                    username = provider_data.get('username')
                    provider_label = f'{provider}_{username}_live'
                    tasks[provider] = con.get(provider_label)
                results = await asyncio.gather(*tasks.values())
                for provider, provider_status in zip(tasks.keys(), results):
                    provider_data = {
                        'username': username,
                        'session_key': self.client_id,
                        'pk': self.user.pk,
                        'channel_name': self.channel_name,
                    }
                    logger.info("Info %s %s", provider, str(provider_status))
                    if provider_status:
                        provider_status: Dict = decode_json(provider_status.decode('utf-8'))
                        self.provider_map[provider] = provider_status.get('server')
                        asyncio.ensure_future(self.provider_action(provider, username, 'auth', provider_data))
                    else:
                        with await self.redis as con:
                            y = [f"{provider}_{_}" for _ in range(0, 4)]
                            r = await con.mget(*y)
                            s = {}
                            for c, d in zip(r, y):
                                if c:
                                    c = int(c)
                                    s[d] = c
                            server_list = sorted(s.items(), key=itemgetter(1))
                            if server_list:
                                server = server_list[0][0]
                                self.provider_map[provider] = server
                                asyncio.ensure_future(self.provider_action(provider, username, 'online', provider_data))
            return {}

    async def cmd_provider_add(self, data: Dict):
        provider = data.get('provider', None)
        if isinstance(provider, str):
            provider = provider.lower()
            if provider in settings.PROVIDERS:
                username = data.get('username', None)
                password = data.get('password', None)
                if isinstance(username, str) and isinstance(password, str):
                    # TODO: Add check if already installed for other user
                    res = await self.check_provider_added(provider, username)
                    user_key = '_'.join(['login', provider, username])
                    if not res:
                        with await self.redis as con:
                            y = [f"{provider}_{_}" for _ in range(0, 4)]
                            r = await con.mget(*y)
                            s = {}
                            for c, d in zip(r, y):
                                if c:
                                    c = int(c)
                                    s[d] = c
                            server_list = sorted(s.items(), key=itemgetter(1))
                            if server_list:
                                server = server_list[0][0]
                                self.provider_map[provider] = server
                        with await self.redis as con:
                            r = await con.execute('setnx', user_key, server)
                            if not r:
                                logger.warning('User login active : %s', username)
                            else:
                                await self.provider_action(provider, username, 'add', {'user_id': int(self.user.id),
                                                                                       'username': username,
                                                                                       'password': password,
                                                                                       'channel_name': self.channel_name})
                                logger.info('Adding user : %s %s', username, str(self.provider_map))

    async def cmd_providers_enabled(self, data: Dict):
        # Send all available user providers
        self.providers = await self.get_user_providers()
        message = {
            'cmd': 'providers_enabled',
            'body': {
                'providers': self.providers,
            }
        }
        return message

    async def cmd_tickets(self, data: Dict):
        provider = data.get('provider', None)
        if isinstance(provider, str):
            provider = provider.lower()
            if provider in settings.PROVIDERS:
                username = self.providers.get(provider).get('username')
                ticket_key = data.get('ticket_key')
                n = data.get('n')
                b = {'ticket_key': ticket_key, 'n': n}
                await self.provider_action(provider, username, 'tickets', b)

    async def cmd_sessions(self, data: Dict):
        provider = data.get('provider')
        username = self.providers.get(provider).get('username')
        await self.provider_action(provider, username, 'sessions', data)
        return {}

    async def cmd_sessions_live(self, data: Dict):
        provider = data.get('provider')
        username = self.providers.get(provider).get('username')
        await self.provider_action(provider, username, 'sessions_live', data)
        return {}

    async def cmd_create_session(self, data: Dict):
        provider = data.get('provider')
        username = self.providers.get(provider).get('username')
        await self.provider_action(provider, username, 'create_session', data)
        return {}

    async def cmd_sessions_stop(self, data: Dict):
        return await self.cmd_sessions_action(data)

    async def cmd_sessions_pause(self, data: Dict):
        return await self.cmd_sessions_action(data)

    async def cmd_sessions_mute(self, data: Dict):
        return await self.cmd_sessions_action(data)

    async def cmd_sessions_action(self, data: Dict):
        provider = data.get('provider')
        username = self.providers.get(provider).get('username')
        await self.provider_action(provider, username, 'sessions_action', data)
        return {}

    def cmd_init_response(self, data: Optional[Dict], exc: Optional[Any]):
        if data:
            self.inner_send(data)

    def cmd_provider_add_response(self, data: Optional[Dict], exc: Optional[Any]):
        pass
        # self.inner_send(message)

    def cmd_providers_enabled_response(self, data: Optional[Dict], exc: Optional[Any]):
        if data:
            return self.inner_send(data)

    def inner_send(self, data: Dict):
        asyncio.create_task(self.session.send_json(data))

    async def on_disconnect(self, close_code):
        for provider_name, provider_data in self.providers.items():
            await self.notify_channel(provider_name, provider_data.get('username'), 'deauth',
                                      {'close_code': close_code})

    @database_sync_to_async
    def get_user_providers(self) -> Dict:
        # Basic django get to db
        providers = self.user.providers.all()
        providers_data = {}
        if providers:
            for provider in providers:
                providers_data[provider.provider] = {'username': provider.username, 'user_id': provider.user_id}
        return providers_data

    @database_sync_to_async
    def get_user_provider_by_id(self, username: str) -> Optional[Providers]:
        # Basic django get to db
        try:
            return Providers.objects.get(username=username)
        except Providers.DoesNotExist:
            return None

    @database_sync_to_async
    def get_installed_providers(self):
        providers = ProviderInstalled.objects.all()
        providers_config = {}
        if providers:
            for provider in providers:
                providers_config[provider.name] = {'id': provider.pk, 'name': provider.name,
                                                   'competitions': provider.competitions}
        return providers_config

    @database_sync_to_async
    def check_provider_added(self, provider: str, username: str) -> bool:
        return Providers.objects.filter(provider=provider, username=username).exists()

    async def provider_action(self, provider_name: str, username: str, provider_action: str, provider_data: Dict):
        await self.notify_channel(provider_name, username, f'{provider_action}', provider_data)

    def parse_payload(self, uri: str, body: Dict) -> Dict:
        return {
            'session_key': self.client_id,
            'uri': uri,
            'pk': self.user.id,
            'body': body
        }

    async def notify_channel(self, channel_name: str, username: str, uri: str, payload: Dict):
        channel_name = f"{self.provider_map.get(channel_name)}_live"
        with await self.redis as con:
            a = self.parse_payload(uri, payload)
            a.setdefault('username', username)
            await con.execute('publish', channel_name, json.dumps(a))

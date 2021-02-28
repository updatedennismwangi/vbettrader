from __future__ import annotations

import signal
import aioredis
import nest_asyncio
import asyncio
import time
from typing import Any, Callable, Coroutine, Dict, Optional, \
    TYPE_CHECKING, Tuple, Type, Union

import aiohttp
from channels.layers import get_channel_layer
from channels_redis.core import RedisChannelLayer
from channels.exceptions import ChannelFull

from vbet.core import settings
from vbet.game.tickets import TicketStatus
from vbet.game.api import auth
from vbet.game.user import User
from vbet.utils import exceptions
from vbet.utils.log import get_logger
from vbet.utils.parser import Resource, encode_json, get_auth_class
from .orm import get_provider_data, save_user
from .socket_manager import SocketManager
from .aaa import TicketManager
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import multiprocessing


if TYPE_CHECKING:
    from vweb.vclient.models import Providers, ProviderInstalled, LiveSession as DbLiveSession
    from vweb.vclient.models import User as UserAdmin, Tickets
    import aioredis

logger = get_logger('provider')

# pylint : disable=import-outside-toplevel


class Provider(multiprocessing.Process):
    loop: Optional[asyncio.AbstractEventLoop] = None
    RUNNING = 'RUNNING'
    PAUSED = 'PAUSED'
    INACTIVE = 'INACTIVE'
    OFFLINE = 'OFFLINE'
    ACTIVE = 'ACTIVE'
    SLEEPING = 'SLEEPING'
    status: str
    provider_name: str
    gid: int
    db_provider: ProviderInstalled
    auth_class: auth.BasicAuth
    users: Dict[str, User]
    user_map: Dict[int, str]
    validating_users: Dict[str, Dict]
    login_users: Dict[str, Dict]
    channel_layer: Optional[RedisChannelLayer]
    redis: Optional[aioredis.Redis] = None
    channel_future: Optional[asyncio.Task]
    channel_con: Optional[aioredis.RedisConnection]
    channel: Optional[aioredis.Channel]
    scanner_future: Optional[asyncio.Task]
    online_future: Optional[asyncio.Task]
    TicketsDb: Type[Tickets]
    UserDb: Type[UserAdmin]
    ProvidersDb: Type[Providers]
    LiveSessionDb: Type[DbLiveSession]
    ProviderInstalledDb: Type[ProviderInstalled]
    sock_manager: SocketManager
    ticket_manager: TicketManager
    scan_interval: int = 3.5
    process_executor: ProcessPoolExecutor
    thread_executor: ThreadPoolExecutor

    def __repr__(self):
        return '[%s-%d]' % (self.provider_name, self.gid)

    def __init__(self, provider_name: str, gid: int):
        super().__init__()
        # Setup authentication class and the SocketManager  instance
        self.provider_name = provider_name
        self.gid = gid
        self.auth_class = get_auth_class(self.name, auth)
        self.sock_manager = SocketManager(self)
        # self.ticket_manager = TicketManager(self)
        self.status = Provider.OFFLINE  # Show server status.
        self.users = {}
        self.user_map = {}
        self.validating_users = {}
        self.channel_future = None
        self.channel_con = None
        self.channel = None
        self.scanner_future = None
        self.login_users = {}

    @property
    def server_name(self):
        return f"{self.provider_name}_{self.gid}"

    @property
    def name(self) -> str:
        return self.provider_name

    @property
    def competitions(self) -> Dict:
        return self.db_provider.competitions

    def run(self):
        logger.info('%r Setting up provider %s', self, multiprocessing.current_process().name)
        # Setup Django
        from vbet.core import vclient

        # Setup event loop, loglevel and default exception handler
        self.loop = asyncio.new_event_loop()
        nest_asyncio.apply(self.loop)
        self.loop.add_signal_handler(signal.SIGINT, self.sig_int_callback)
        self.loop.set_debug(settings.LOOP_DEBUG)

        self.loop.run_until_complete(self.setup())
        self.process_executor = ProcessPoolExecutor(max_workers=settings.PROCESS_POOL_WORKERS)
        self.thread_executor = ThreadPoolExecutor(max_workers=settings.THREAD_POOL_WORKERS)

        try:
            self.status = Provider.ACTIVE
            self.loop.run_forever()
        except KeyboardInterrupt:
            logger.info('%r Provider Graceful shutdown initialized', self)
            try:
                future = self.loop.create_task(self.clean_up())
                future.add_done_callback(self.clean_up_callback)
                self.loop.run_forever()
            except KeyboardInterrupt:
                pass
            else:
                logger.info('%r Provider Graceful shutdown success', self)
            finally:
                self.loop.close()
                logger.info('%r Provider terminated', self)

    async def setup(self):
        # Db setup
        from vbet.core.orm import load_provider_data
        self.db_provider = await load_provider_data(self.provider_name)

        # Setup socketManager  instance
        await self.sock_manager.setup()

        # Redis and channel layer setup
        await self.setup_redis()

        # channel_future reads and processes payloads from `provider_live` channel in redis
        self.channel_future = asyncio.create_task(self.channel_reader())

        # scanner_future scans every scan_interval to manage the provider
        self.scanner_future = asyncio.create_task(self.scanner())

    async def setup_redis(self):
        # Initialize django channels channel layer
        self.channel_layer = get_channel_layer()
        # Create global redis pool
        self.redis = await aioredis.create_redis_pool(
            settings.REDIS_URI,
            minsize=settings.REDIS_POOL_MIN,
            maxsize=settings.REDIS_POOL_MAX
        )

    async def channel_reader(self):
        await self.online_updater()
        with await self.redis as con:
            try:
                self.channel_con = con
                name = f'{self.provider_name}_{self.gid}_live'
                logger.info('%r Channel reader online. (name=%s)', self, name)
                res = await con.subscribe(name)
                self.channel = res[0]  # type: aioredis.Channel
                while await self.channel.wait_message():
                    try:
                        payload = await self.channel.get_json()  # type: Dict
                    except ValueError:
                        continue
                    if payload:
                        session_key = payload.get('session_key')
                        uri = payload.get('uri')
                        body = payload.get('body')
                        username = payload.get('username')
                        callback = getattr(self, f'provider_{uri}_uri', None)
                        if callback:
                            callback: Callable[[str, str, Dict], Coroutine[Any]]
                            channel_name = body.get('channel_name')
                            asyncio.create_task(callback(session_key, channel_name, body))
                        else:
                            user = self.get_user(username=username)
                            if user:
                                ws_session = user.ws_sessions.get(session_key)
                                if ws_session:
                                    callback: Callable[[Dict], Coroutine[Any]] = getattr(ws_session, f'{uri}_uri')
                                    if callback:
                                        asyncio.create_task(callback(body))
                                else:
                                    if uri == 'auth':
                                        user.add_ws_session(session_key, body)
                                        ws_session = user.ws_sessions.get(session_key)
                                        await ws_session.auth_uri({})
            except asyncio.CancelledError:
                self.channel_con.close()
                logger.info('%r Channel reader offline. (name=%s)', self, name)

    async def scanner(self):
        logger.debug('%r Scanner started', self)
        while True:
            for user in self.users.values():
                user_rem = []
                async with user.ticket_manager.pool_lock:
                    for game_id, competition_tickets in user.ticket_manager.active_tickets.items():
                        for ticket_key, ticket in competition_tickets.items():
                            if ticket.status == TicketStatus.DISCARD:
                                user_rem.append(ticket)
                            elif ticket.status == TicketStatus.VOID:
                                user_rem.append(ticket)
                                ticket.on_void()
                                await ticket.save()
                                continue
                            elif ticket.status == TicketStatus.SENT:
                                if time.time() - ticket.sent_time > 5:
                                    logger.warning('%r %r Ticket Sent But status unknown :  %r', self, user, ticket)
                                    payload = user.resource_ticket_by_id(2)
                                    socket = await user.ticket_manager.get_available_socket()
                                    socket, xs = user.send(Resource.TICKETS_FIND_BY_ID, payload,
                                                           socket_id=socket.socket_id)
                                    user.ticket_check[xs] = (ticket.game_id, ticket.ticket_key)
                                    logger.warning('%r %r Please validate lost ticket %d %f xs : %d', self,
                                                   user, ticket.ticket_id, ticket.total_won, xs)
                                pass
                            elif ticket.status == TicketStatus.SUCCESS and ticket.resolved and\
                                    ticket.status != TicketStatus.DISCARD:
                                if ticket.demo:
                                    if ticket.total_won > 0:
                                        ticket.ticket_status = 'PAIDOUT'
                                        ticket.db_ticket.won_data = {'won': ticket.total_won, 'stake': ticket.stake}
                                    else:
                                        ticket.ticket_status = 'LOST'
                                        ticket.db_ticket.won_data = {'won': ticket.total_won, 'stake': ticket.stake}
                                    await ticket.save()
                                    ticket.status = TicketStatus.DISCARD
                                    user_rem.append(ticket)
                                else:
                                    if ticket.total_won > 0:
                                        payload = user.resource_ticket_by_id(1, ticket.ticket_id)
                                        socket = await user.ticket_manager.get_available_socket()
                                        socket, xs = user.send(Resource.TICKETS_FIND_BY_ID, payload,
                                                               socket_id=socket.socket_id)
                                        logger.warning('%r Please validate ticket %d %f xs : %d',
                                                       user, ticket.ticket_id, ticket.total_won, xs)
                                    else:
                                        ticket.on_lost()
                                        await ticket.save()
                                        ticket.status = TicketStatus.DISCARD
                                        if time.time() - ticket.sent_time > 5:
                                            user_rem.append(ticket)
                # Discard marked tickets
                for t in user_rem:
                    await user.ticket_manager.remove_ticket(t)

            await asyncio.sleep(self.scan_interval)

    async def online_updater(self):
        with await self.redis as con:
            try:
                k = f"{self.provider_name}_{self.gid}"
                await con.set(k, len(self.users))
            except asyncio.CancelledError:
                pass

    def send_to_session(self, username: str, session_key: str, uri: str, body: Dict, channel_name: str = None):
        if channel_name:
            asyncio.create_task(self._sender(session_key, channel_name, uri, body))
        else:
            user = self.get_user(username=username)
            if user:
                ws_session = user.ws_sessions.get(session_key)
                if ws_session:
                    asyncio.create_task(self._sender(session_key, ws_session.channel_name, uri, body))

    async def _sender(self, session_key: str, channel_name: str, uri: str, body: Dict):
        payload = {
            'type': 'chat.message',
            'provider': self.name,
            'uri': uri,
            'session_key': session_key,
            'body': encode_json(body)
        }
        try:
            await self.channel_layer.send(channel_name, payload)
        except ChannelFull:
            pass

    # User management
    async def validate_user(self, pk: id, username: str) -> Providers:
        provider = await get_provider_data(pk, self.name)  # type: Providers
        if provider:
            cookies = provider.token.get('cookies')  # type: Dict
            token = provider.token.get('token')  # type: str
            res = await self.auth_class.sync_balance(username, token, cookies,
                                                     self.sock_manager.http)
            if res.get('success'):
                return provider
            raise exceptions.ExpiredUserCache(username)
        raise exceptions.InvalidUserCache(username)

    async def login_user(self, username: str, password: str) -> \
            Optional[Tuple[str, Dict]]:
        http = aiohttp.ClientSession(
            headers=auth.HEADERS)  # type: aiohttp.ClientSession
        logger.info('%r login init %s %s', self, username, password)
        unit_id, token, cookies = await self.auth_class.login_password(username,
                                                                       password,
                                                                       http)
        logger.info('%r login complete %s %s', self, username, unit_id)
        data = {'cookies': cookies, 'id': unit_id, 'token': token}  # type: Dict
        await http.close()
        return username, data

    def user_validation_callback(self, future: asyncio.Task):
        exc = future.exception()  # TODO: Type checks
        validate_payload: Optional[Dict]
        if isinstance(exc, (exceptions.InvalidUserCache, exceptions.ExpiredUserCache)):
            logger.warning('%r user validation %s', self, exc)
            validate_payload = self.validating_users.pop(exc.username)
            session_key = validate_payload.get('session_key')  # type: str
            channel_name = validate_payload.get('channel_name')  # type: str
            payload = {'body': exc.__str__(), 'success': False}
            if session_key:
                self.send_to_session(exc.username, session_key, 'init', payload, channel_name=channel_name)
        else:
            provider = future.result()
            try:
                validate_payload = self.validating_users.pop(provider.username)
            except KeyError:
                pass
            else:
                user = self.create_user(provider)  # type: User
                session_key = validate_payload.get('session_key')  # type: str
                user.add_ws_session(session_key, validate_payload.get('body'))
                session = user.ws_sessions.get(session_key)
                asyncio.ensure_future(session.auth_uri({}))

    def user_login_callback(self, future: asyncio.Task):
        exc = future.exception()  # TODO: Type checks
        login_payload: Union[Dict, None]
        if isinstance(exc, exceptions.InvalidUserAuthentication):
            usr_key = f'login_{self.name}_{exc.username}'
            logger.warning('%r Error login %s', self, exc)
            login_payload = self.login_users.pop(exc.username)
            session_key = login_payload.get('session_key')  # type: str
            channel_name = login_payload.get('channel_name')  # type: str
            y = exc.body
            y.setdefault('provider', self.name)
            payload = {'body': y, 'success': False}
            if channel_name:
                self.send_to_session(exc.username, session_key, 'provider_add', payload, channel_name=channel_name)
        else:
            data = future.result()  # type: Tuple[str, Dict]
            username, user_data = data[0], data[1]
            usr_key = f'login_{self.name}_{username}'
            login_payload = self.login_users.pop(username)
            user_id = login_payload.get('body', {}).get('user_id', {})
            asyncio.create_task(
                save_user(user_id, username, self.name, user_data))
            logger.info('%r User cached (username=%s)', self, username)
            session_key = login_payload.get('session_key')  # type: str
            channel_name = login_payload.get('channel_name')  # type: str
            user_data.setdefault('username', username)
            user_data.setdefault('provider', self.name)
            payload = {'body': user_data, 'success': True}
            if session_key:
                self.send_to_session(username, session_key, 'provider_add', payload, channel_name=channel_name)
        asyncio.ensure_future(self.redis.delete(usr_key))

    def create_user(self, provider: Providers) -> User:
        user = self.users.setdefault(provider.username, User(self, provider))
        asyncio.ensure_future(self.register_online(user))
        self.user_map[user.user_id] = provider.username
        user.online()
        return user

    def delete_user(self, provider: Providers):
        user = self.users.pop(provider.username)
        asyncio.ensure_future(self.register_offline(user))
        del self.user_map[user.user_id]
        user.offline()

    def get_user(self, username: str = '', user_id: int = None):
        if user_id:
            username = self.user_map.get(user_id)
        return self.users.get(username)

    async def register_online(self, user: User):
        with await self.redis as con:
            await con.set(f'{self.name}_{user.username}_live', encode_json({'status': user.status,
                                                                            'server': self.server_name}))
        await self.online_updater()

    async def register_offline(self, user: User):
        with await self.redis as con:
            await con.delete(f'{self.name}_{user.username}_live')
        await self.online_updater()

    # API calls
    async def provider_online_uri(self, session_key: str, channel_name: str, body: Dict):
        username = body.get('username')  # type: str
        pk = body.get('pk')
        body.setdefault('games', self.competitions)
        user = self.users.get(username)
        validating_user = self.validating_users.get(username)
        if not user and not validating_user:
            future = asyncio.create_task(self.validate_user(pk, username))
            future.set_name(f'validate_{self.name}_{username}')
            future.add_done_callback(self.user_validation_callback)
            body = dict(future=future, session_key=session_key, channel_name=channel_name, body=body)
            self.validating_users.setdefault(username, body)

    async def provider_add_uri(self, session_key: str, channel_name: str, body: Dict):
        username = body.get('username')  # type: Union[str, Any]
        password = body.get('password')  # type: Union[str, Any]
        if isinstance(username, str) and isinstance(password, str):
            if username not in self.login_users:
                future = asyncio.create_task(
                    self.login_user(username, password))
                future.add_done_callback(self.user_login_callback)
                self.login_users[username] = {'future': future,
                                              'body': body,
                                              'channel_name': channel_name,
                                              'session_key': session_key
                                              }

    async def provider_auth_uri(self, session_key: str, channel_name: str,  body: Dict):
        username = body.get('username')
        user = self.users.get(username)
        if user:
            user.add_ws_session(session_key, body)
            session = user.ws_sessions.get(session_key)
            asyncio.ensure_future(session.auth_uri({}))
        else:
            await self.provider_online_uri(session_key, channel_name, body)

    # Shutdown
    async def wait_closed(self):
        pending = {}  # type: Dict
        for username, user in self.users.items():
            pending[username] = asyncio.create_task(user.wait_closed())
        if pending:
            done, p = await asyncio.wait(list(pending.values()),
                                         return_when=asyncio.ALL_COMPLETED)

        await self.sock_manager.wait_closed()

    async def clean_up_scanners(self):
        await self.wait_closed()
        if self.channel_future:
            state = self.channel_future.cancel()
            while not state:
                state = self.channel_future.cancel()
        if self.scanner_future:
            state = self.scanner_future.cancel()
            while not state:
                state = self.channel_future.cancel()
        for username in self.users:
            pipe = self.redis.pipeline()
            key = f'{self.name}_{username}_live'
            pipe.delete(key)
            await pipe.execute()
        logger.info('%r Clean up scanners complete', self)

    async def clean_up(self):
        logger.info('%r Closing provider %s', self, multiprocessing.current_process().name)
        # Close redis pool
        await self.clean_up_scanners()
        self.redis.close()
        await self.redis.wait_closed()
        # Close django channels_layer
        await self.channel_layer.close_pools()
        self.process_executor.shutdown()
        self.thread_executor.shutdown()
        logger.info('%r Shutdown okay provider %s', self, multiprocessing.current_process().name)

    def clean_up_callback(self, future: asyncio.Task):
        # Log any errors in the clean_up coroutine and stop event loop
        if future.exception():
            logger.exception('Error shutting down %s', future.exception())
        else:
            logger.info('%r Closing provider loop %s', self, multiprocessing.current_process().name)
        self.loop.stop()

    @classmethod
    def cancel_tasks(cls):
        # Cancel all pending tasks
        tasks = asyncio.gather(*asyncio.Task.all_tasks(),
                               return_exceptions=True)
        tasks.add_done_callback(lambda a: asyncio.get_event_loop().stop())

    def sig_int_callback(self):
        # Trigger clean shutdown
        logger.info('%r Graceful shutdown requested  ', self)
        raise KeyboardInterrupt

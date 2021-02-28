from __future__ import annotations

import asyncio
import operator
import socket as sock
import time
from typing import Dict, List, Optional, TYPE_CHECKING, Tuple

import aiohttp
import websockets

from vbet.utils.log import get_logger
from vbet.utils.parser import decode_json, encode_json, inspect_websocket_response, Resource
from vbet.utils.executor import process_exec
from concurrent.futures import Future

if TYPE_CHECKING:
    from .provider import Provider

logger = get_logger('sockets')


class Stream:
    socket: Socket
    status: str
    username: str
    user_id: int
    stream_id: int
    online_hash: str
    client_id: str
    last_used: float
    xs_pool: Dict[int]
    hash_future: Optional[asyncio.Task]
    ready_hash: bool

    PROFILE: str = 'WEB'
    AUTHORIZED = 'AUTHORIZED'
    READY = 'READY'
    ANONYMOUS = 'ANONYMOUS'
    UNAUTHENTICATED = 'UNAUTHENTICATED'

    def __init__(self, socket: Socket, username: str, user_id: int, stream_id: int):
        self.socket = socket
        self.status = Stream.ANONYMOUS
        self.stream_id = stream_id
        self.online_hash = ''
        self.username = username
        self.user_id = user_id
        self.client_id = ''
        self.last_used = time.time()
        self.xs_pool = {}
        self.hash_future = None
        self.ready_hash = False

    def __repr__(self):
        return '[%s:%d]' % (self.username, self.stream_id)

    def acquire(self, xs: int, body: Dict):
        self.xs_pool[xs] = body
        self.last_used = time.time()

    def init(self):
        if isinstance(self.hash_future, asyncio.Task):
            if not self.hash_future.done():
                return
        auth_class = self.socket.socket_manager.provider.auth_class
        user = self.socket.socket_manager.provider.get_user(username=self.username)
        self.hash_future = asyncio.create_task(
            auth_class.login_hash(self.username,
                                  self.user_id,
                                  self.socket.socket_id,
                                  user.cookies,
                                  self.socket.socket_manager.http))
        self.hash_future.add_done_callback(self.hash_complete)

    def hash_complete(self, future: asyncio.Task):
        exc = future.exception()
        if exc:
            logger.warning('%r %r hash_complete %s', self.socket, self, exc)
        else:
            self.online_hash = future.result()
            self.status = self.READY
            # Send login if open socket
            if self.socket.status == Socket.CONNECTED:
                body = {'onlineHash': self.online_hash, 'profile': Stream.PROFILE}
                user = self.socket.socket_manager.provider.get_user(user_id=self.user_id)
                user.send(Resource.LOGIN, body, socket_id=self.socket.socket_id)
                self.ready_hash = False
            else:
                self.ready_hash = True

    def reset(self):
        self.status = Stream.ANONYMOUS
        self.client_id = ''
        self.online_hash = ''
        if isinstance(self.hash_future, asyncio.Task):
            if not self.hash_future.done():
                self.hash_future.cancel()


class Socket:
    ws: Optional[websockets.WebSocketClientProtocol]
    socket_manager: SocketManager
    socket_id: int
    max_users: int
    users: Dict[int, Stream]
    last_used: float
    last_tss: float
    xs: int
    alive: bool
    status: int
    read_task: Optional[asyncio.Task]
    response_tasks: Dict[str, asyncio.Task]
    error_code: int
    xs_pool: Dict[int, int]

    CONNECTING = 1
    CONNECTED = 2
    NOT_AUTHORIZED = 3
    CLOSED = 4
    READY = 5

    MESSAGE_TIMEOUT = 40
    CONNECT_RETRY_TIMEOUT = 30

    CLOSE_CODE = 100
    MESSAGE_TIMEOUT_CODE = 102
    ERROR_CODE = 103

    def __init__(self, socket_manager: SocketManager, socket_id: int, max_users: int = 10):
        self.socket_manager = socket_manager
        self.socket_id = socket_id
        self.max_users = max_users
        self.users = {}
        self.last_used = time.time()
        self.last_tss = time.time()
        self.xs = -1
        self.alive = True
        self.read_task = None
        self.response_tasks = {}
        self.error_code = Socket.CLOSE_CODE
        self.status = Socket.CLOSED
        self.xs_pool = {}

    def __repr__(self):
        return '%r [%d]' % (self.socket_manager, self.socket_id)

    def add_user(self, user_data: Dict) -> Stream:
        user_id = user_data.get('user_id')
        stream_id = user_data.get('stream_id')
        username = user_data.get('username')
        stream = self.users.setdefault(user_id, Stream(self, username, user_id, stream_id))
        # Start login hash if socket is online
        if self.status == Socket.CONNECTED:
            stream.init()
        return stream

    def has_user(self, user_id: int) -> bool:
        return user_id in self.users

    def get_xs(self) -> int:
        self.xs += 1
        return self.xs

    def acquire(self, xs: int, user_id: int):
        self.last_used = time.time()
        self.xs_pool[xs] = user_id

    def sync_users(self):
        for user_id in self.users:
            user = self.socket_manager.provider.get_user(user_id=user_id)
            user.send(Resource.SYNC, {}, socket_id=self.socket_id)

    async def connect(self):
        retry_connect: bool = True
        while retry_connect:
            self.error_code = Socket.CLOSE_CODE
            retry_connect = False
            self.status = Socket.CONNECTING
            try:
                logger.info('%r Ws opening', self)
                async with websockets.connect('wss://virtual-proxy.golden-race.net:9443/vs', close_timeout=2) as con:
                    self.ws = con
                    self.status = Socket.CONNECTED
                    logger.debug('%r Ws connected (address=%s)', self, self.ws.remote_address)
                    await self.on_connect()
                    while True:
                        message = await self.reader(Socket.MESSAGE_TIMEOUT)
                        if message:
                            await self.process_message(message)
                        else:
                            if self.error_code == Socket.MESSAGE_TIMEOUT_CODE:
                                logger.debug('%r Ws message timeout. Retrying manual sync', self)
                                try:
                                    pong = await self.ws.ping()
                                    await asyncio.wait_for(pong, timeout=20)
                                except (asyncio.TimeoutError, asyncio.CancelledError, websockets.ConnectionClosed):
                                    logger.debug('%r Ws message timeout. Respawn connection', self)
                                    break
                                else:
                                    logger.debug('%r Ws message timeout. Connection restored', self)
                                    continue
                            else:
                                break
                self.status = Socket.CLOSED
                logger.debug('%r Ws disconnected', self)
            except (ConnectionError, websockets.InvalidHandshake, sock.gaierror) as exc:
                retry_connect = True
                logger.warning('%r Ws failed %s', self, exc)
                await asyncio.sleep(Socket.CONNECT_RETRY_TIMEOUT)
        tasks = []
        for user_id, stream in self.users.items():
            user = self.socket_manager.provider.get_user(user_id=user_id)
            t = user.stream_lost(stream.stream_id)
            tasks.append(t)
        await asyncio.gather(*tasks)
        return self.socket_id

    async def on_connect(self):
        for user_id, stream in self.users.items():
            if stream.ready_hash and stream.status == Stream.READY:
                user = self.socket_manager.provider.get_user(user_id=user_id)
                body = {'onlineHash': stream.online_hash, 'profile': stream.PROFILE}
                user.send(Resource.LOGIN, body, socket_id=self.socket_id)
            elif stream.status == Stream.ANONYMOUS:
                # Start all login hash
                stream.init()

    async def sender(self, payload: Dict):
        if self.ws.state == 1:
            try:
                await self.ws.send(encode_json(payload))
            except websockets.ConnectionClosed as err:
                logger.warning('Sender failed to complete %s', payload)
        else:
            logger.warning('Discard, closed %s', str(payload))

    async def process_message(self, message: str):

        # from vbet.core.vbet import Vbet
        # TODO
        # data = process_exec(Vbet.process_executor, inspect_websocket_response, decode_json(message))
        data = inspect_websocket_response(decode_json(message))
        if data:
            # TODO
            if isinstance(data, Future):
                data = data.result()
            if isinstance(data, tuple):
                (xs, resource, status_code, valid_response, body) = data
                try:
                    user_id = self.xs_pool.pop(xs)
                    stream = self.get_user_stream(user_id)
                    request_data = stream.xs_pool.pop(xs)
                except KeyError:
                    pass
                else:
                    # logger.info('%r %d %s %s', self, user_id, resource, str(request_data))
                    user = self.socket_manager.provider.get_user(user_id=user_id)
                    task_name = f'{user_id}_{stream.stream_id}_{xs}'
                    task = self.response_tasks.setdefault(task_name,
                                                          asyncio.create_task(
                                                              user.receive(
                                                                  self.socket_id,
                                                                  xs,
                                                                  resource,
                                                                  valid_response,
                                                                  body))
                                                          )
                    task.set_name(task_name)
                    task.add_done_callback(self.dispatch_callback)

    async def reader(self, timeout: float):
        try:
            payload = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
            self.last_tss = time.time()
            return payload
        except asyncio.TimeoutError:
            self.error_code = Socket.MESSAGE_TIMEOUT_CODE
        except websockets.ConnectionClosed as err:
            if isinstance(err, websockets.ConnectionClosedError):
                self.error_code = Socket.ERROR_CODE
                logger.warning('%r Ws close error : %d %s', self, err.code, err.reason)
            else:
                self.error_code = Socket.CLOSE_CODE
                logger.debug('%r Ws close normal : %d %s', self, err.code, err.reason)

    def get_user_stream(self, user_id: int) -> Optional[Stream]:
        return self.users.get(user_id)

    def dispatch_callback(self, future_task: asyncio.Task):
        self.response_tasks.pop(future_task.get_name())
        exc = future_task.exception()
        if exc:
            logger.error('%r Dispatch error %s %s', self, future_task.get_name(), exc)

    async def wait_closed(self):
        self.alive = False
        if self.status == Socket.CONNECTED:
            await self.ws.close()


class SocketManager:
    provider: Provider
    socket_id: int
    min_sockets: int
    max_sockets: int
    sockets: Dict[int, Socket]
    socket_tasks: Dict[int, asyncio.Task]
    socket_map: Dict[int, List[int]]
    http: Optional[aiohttp.ClientSession]

    def __init__(self, manager: Provider, min_sockets: int = 5, max_sockets: int = 10):
        self.socket_id = 0
        self.provider = manager
        self.min_sockets = min_sockets
        self.max_sockets = max_sockets
        self.sockets = {}
        self.socket_tasks = {}
        self.socket_map = {}
        self.http = None

    def __repr__(self):
        return '[%s]' % self.provider.name

    async def setup(self):
        logger.info('%r Starting socket pool (min=%d, max=%d)', self, self.min_sockets, self.max_sockets)
        self.http = aiohttp.ClientSession()
        asyncio.create_task(self.keep_alive())

    def create_socket(self):
        self.socket_id += 1
        socket = Socket(self, self.socket_id)
        self.sockets[self.socket_id] = socket
        return socket

    def get_socket(self, socket_id: int, user_id: int = None):
        s = self.sockets.get(socket_id)
        return s

    def close_user_sockets(self, user_id: int):
        if self.sockets:
            fds = []
            for s_id, s in self.sockets:
                if s.get_user_stream(user_id):
                    a = len(s.users)
                    fds.append((a, s))
            if fds:
                for _ in fds:
                    k, v = _
                    if k > 1:
                        v.users.pop(user_id)

    def add_user_socket(self, user_id: int, stream_id: int, reuse: bool = True):
        socket: Optional[Socket] = None
        if reuse:
            if self.sockets:
                sockets = sorted(self.sockets.values(), key=operator.attrgetter('last_used'))
                for s in sockets:
                    if not s.get_user_stream(user_id) and len(s.users) < s.max_users:
                        socket = s
                        break
        if not socket:
            socket = self.create_socket()
            task = self.socket_tasks.setdefault(socket.socket_id, asyncio.create_task(socket.connect()))
            task.set_name('sock_connect_%s' % socket.socket_id)
            task.add_done_callback(self.clean_socket)
        user_map = self.socket_map.setdefault(user_id, [])
        user_map.append(socket.socket_id)
        socket.add_user({'user_id': user_id, 'username': self.provider.user_map.get(user_id), 'stream_id': stream_id})
        return socket

    def filter_user_sockets(self, user_id: int, sort: bool = True, authorized: bool = True) -> List[Socket]:
        sockets = []
        user_map = self.socket_map.get(user_id, [])
        if user_map:
            for socket_id in user_map:
                socket = self.sockets.get(socket_id)
                if socket.status == socket.CONNECTED:
                    if socket.has_user(user_id):
                        stream = socket.users.get(user_id)
                        if stream.online_hash:
                            if authorized:
                                stream = socket.get_user_stream(user_id)
                                if stream.status != stream.AUTHORIZED:
                                    continue
                            sockets.append(socket)
            if sockets and sort:
                sockets.sort(key=operator.attrgetter('last_used'))
        return sockets

    def send(self, user_id: int, resource: str, body: Dict, method: str = 'GET',
             socket_id: int = None) -> Tuple[int, int]:
        auth_flag = True
        if resource == Resource.LOGIN:
            auth_flag = False
        sockets = self.filter_user_sockets(user_id, authorized=auth_flag)
        if not sockets:
            return -1, -1
        if socket_id:
            socket = self.sockets.get(socket_id, sockets[0])
        else:
            socket = sockets[0]
        stream = socket.get_user_stream(user_id)
        xs = socket.get_xs()
        socket.acquire(xs, user_id)
        stream.acquire(xs, {'resource': resource})
        headers = {'Content-Type': 'application/json'}
        if resource != Resource.LOGIN:
            headers['clientId'] = stream.client_id
        data = {
            'type': 'REQUEST',
            'xs': xs,
            'ts': int(time.time() * 1000),
            'req': {
                'method': method,
                'query': {} if method == 'POST' else body,
                'headers': headers,
                'resource': resource,
                'basePath': '/api/client/v0.1',
                'host': 'wss://virtual-proxy.golden-race.net:9443'
            }
        }
        if method == 'POST':
            data['req']['body'] = body
        asyncio.create_task(socket.sender(data))
        return xs, socket.socket_id

    def clean_socket(self, future: asyncio.Task):
        socket_id = future.result()
        socket = self.sockets.get(socket_id)
        if socket:
            task = self.socket_tasks.pop(socket_id)
            del task
            if not socket.alive:
                logger.debug('%r Socket closed %r', self, socket)
            else:
                logger.warning('%r Socket lost %r', self, socket)
                for stream in socket.users.values():
                    stream.reset()
                new_task = self.socket_tasks.setdefault(socket_id, asyncio.create_task(socket.connect()))
                new_task.set_name('sock_connect_%s' % socket.socket_id)
                new_task.add_done_callback(self.clean_socket)

    async def keep_alive(self):
        logger.debug('%r Session keep alive', self)
        while True:
            self.sync_streams()
            await asyncio.sleep(30)

    def sync_streams(self):
        for socket_id, socket in self.sockets.items():
            if socket.status == Socket.CONNECTED:
                socket.sync_users()

    async def wait_closed(self):
        tasks = []
        for socket in self.sockets.values():
            tasks.append(socket.wait_closed())
        if tasks:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)

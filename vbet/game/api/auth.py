import asyncio
from http.cookies import Morsel, SimpleCookie
from typing import Dict, Optional

import aiohttp

import vbet
from vbet.core import settings
from vbet.utils.exceptions import InvalidUserAuthentication, InvalidUserHash
from vbet.utils.log import get_logger

logger = get_logger('auth')

HEADERS = {
    'User-Agent': f'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:84.0) Gecko/20100101 Firefox/84.0'
}

WSS_URL = 'wss://virtual-proxy.golden-race.net:9443/vs'


class BasicAuth:
    name = 'basic'
    COOKIES_URL = ''

    def __init__(self):
        pass

    def __repr__(self):
        return '(provider_auth=%s)' % self.name

    async def login_hash(self, username: str, user_id: int, socket_id: int, cookies: Dict, http: aiohttp.ClientSession):
        pass

    async def login_password(self, username: str, password: str, http: aiohttp.ClientSession):
        pass

    async def sync_balance(self, username: str, token: str, cookies: Dict, http: aiohttp.ClientSession):
        pass


class BetikaAuth(BasicAuth):
    name = settings.BETIKA
    HASH_URL = 'https://api-golden-race.betika.com/betikagr/Login'
    LOGIN_URL = 'https://api.betika.com/v1/login'
    COOKIES_URL = 'https://api.betika.com'
    BALANCE_URL = 'https://api.betika.com/v1/balance'

    async def login_hash(self, username: str, user_id: int, socket_id: int, cookies: Dict, http: aiohttp.ClientSession):
        try:
            pin_hash: Optional[str] = None
            while pin_hash is None:
                try:
                    response = await http.post(
                        BetikaAuth.HASH_URL,
                        json={'profile_id': user_id}, cookies=cookies)  # type: aiohttp.ClientResponse
                    data = await response.json(content_type="text/json")  # type: Dict
                    if response.status == 200:
                        pin_hash = data.get('onlineHash')  # type: Optional[str]
                        if isinstance(pin_hash, str):
                            return pin_hash
                        raise InvalidUserHash(username, response.status, body=data)
                except (aiohttp.ClientConnectionError, InvalidUserHash, ConnectionError) as err:
                    logger.error('(%r, username=%s, sock_id=%d) login hash %s', self, username, socket_id, str(err))
                    await asyncio.sleep(30)
        except asyncio.CancelledError:
            pass

    async def login_password(self, username: str, password: str, http: aiohttp.ClientSession):
        unit_id: Optional[int] = None
        token: Optional[str] = None
        cookies: Optional[dict] = {}
        while unit_id is None:
            try:
                payload = {
                    'mobile': username,
                    'password': password,
                    'remember': True,
                    'src': 'DESKTOP'
                }
                response = await http.post(self.LOGIN_URL, json=payload)  # type: aiohttp.ClientResponse
                data = await response.json(content_type="application/json")  # type: Dict
                if response.status == 200:
                    token = data.get('token')  # type: Optional[str]
                    user_data = data.get('data', {})  # type: Dict
                    user = user_data.get('user', {})  # type: Dict
                    unit_id = user.get('id')  # type: Optional[int]
                    cookies = http.cookie_jar.filter_cookies(self.COOKIES_URL)  # type: Dict
                    if not token or not unit_id:
                        raise InvalidUserAuthentication(
                            username,
                            password,
                            InvalidUserAuthentication.UNKNOWN_ERROR, body=data)
                    return unit_id, token, cookies
                raise InvalidUserAuthentication(
                    username,
                    password,
                    InvalidUserAuthentication.INVALID_CREDENTIALS, body=data)
            except (aiohttp.ClientConnectionError, ConnectionError) as err:
                logger.error('(%r username=%s) login user %s', self, username, str(err))
                await asyncio.sleep(30)

    async def sync_balance(self, username: str, token: str, cookies: Dict, http: aiohttp.ClientSession):
        user_data: Dict = {}
        while not user_data:
            try:
                response = await http.post(self.BALANCE_URL, json={'token': token},
                                           cookies=cookies)  # type: aiohttp.ClientResponse
                data = await response.json()  # type: Dict
                if response.status == 200:
                    user_data.setdefault('success', True)
                    user_data.setdefault('balance', data.get('data', {}).get('balance'))
                    return user_data
                user_data.setdefault('success', False)
            except (aiohttp.ClientConnectionError, InvalidUserHash, ConnectionError) as err:
                logger.error('(%r username=%s) sync balance %s', self, username, str(err))
                await asyncio.sleep(30)


class MozzartAuth(BasicAuth):
    name = settings.MOZZART
    HASH_URL = 'https://www.mozzartbet.co.ke/golden-race-me'
    LOGIN_URL = 'https://www.mozzartbet.co.ke/auth'
    COOKIES_URL = 'https://www.mozzartbet.co.ke'
    BALANCE_URL = 'https://www.mozzartbet.co.ke/myBalances'

    async def login_hash(self, username: str, user_id: int, socket_id: int, cookies: Dict, http: aiohttp.ClientSession):
        pin_hash: Optional[str] = None
        while pin_hash is None:
            try:
                response = await http.get(self.HASH_URL, cookies=cookies)  # type: aiohttp.ClientResponse
                data = await response.json(content_type="application/json")  # type: Dict
                if response.status == 200:
                    pin_hash = data.get('onlineHash', None)  # type: Optional[str]
                    if isinstance(pin_hash, str):
                        return pin_hash
                    raise InvalidUserHash(username, response.status, body=data)
            except (aiohttp.ClientConnectionError, InvalidUserHash) as err:
                logger.error('(%r, username=%s, sock_id=%d) login hash %s', self, username, socket_id, str(err))
                await asyncio.sleep(30)

    async def login_password(self, username: str, password: str, http: aiohttp.ClientSession):
        unit_id: Optional[int] = None
        token: Optional[str] = None
        cookies: Optional[dict] = {}
        while unit_id is None:
            try:
                fingerprint = 'a39ad90130543e3547bf7b2bda9369'
                body = {
                    'fingerprint': fingerprint,
                    'isCasinoPage': False,
                    'password': password,
                    'username': username
                }
                response = await http.post(MozzartAuth.LOGIN_URL, json=body)  # type: aiohttp.ClientResponse
                data = await response.json(content_type="application/json")  # type: Dict
                if response.status == 200:
                    status = data.get('status', None)  # type: Optional[str]
                    if not isinstance(status, str):
                        raise InvalidUserAuthentication(username, password,
                                                        InvalidUserAuthentication.UNKNOWN_ERROR, body=data)
                    elif status == 'IVALID_CREDENTIALS':
                        raise InvalidUserAuthentication(username, password,
                                                        InvalidUserAuthentication.INVALID_CREDENTIALS, body=data)
                    user = data.get('user', {})  # type: Dict
                    unit_id = user.get('userId', None)  # type: Optional[int]
                    cookies = response.cookies.items()
                    _cookies = {}  # type: Dict
                    cookie_entry: SimpleCookie
                    for cookie_entry in cookies:
                        cookie = cookie_entry[1]  # type: Morsel
                        _cookies[cookie.key] = cookie.value
                    cookies = _cookies
                    return unit_id, token, cookies
                raise InvalidUserAuthentication(
                    username,
                    password,
                    InvalidUserAuthentication.INVALID_CREDENTIALS, body=data)
            except aiohttp.ClientConnectionError as err:
                logger.error('(%r, username=%s) login user timeout %s', self, username, err)
                await asyncio.sleep(30)

    async def sync_balance(self, username: str, token: str, cookies: Dict, http: aiohttp.ClientSession):
        user_data: Dict = {}
        while not user_data:
            try:
                body = {
                    "dontFetchOmegaBalance": True,
                    "shouldReloadOmegaBonuses": True,
                    "username": username
                }
                response = await http.post(self.BALANCE_URL, json=body,
                                           cookies=cookies)  # type: aiohttp.ClientResponse
                data = await response.json()  # type: Dict
                if response.status == 200:
                    user_data.setdefault('success', True)
                    user_data.setdefault('balance', data.get('bettingBalance'))
                    return user_data
                user_data.setdefault('success', False)
            except (aiohttp.ClientConnectionError, InvalidUserHash) as err:
                logger.error('(%r username=%s) sync balance %s', self, username, str(err))
                await asyncio.sleep(30)


class MerryAuth(BasicAuth):
    name = settings.MOZZART
    HASH_URL = 'https://www.mozzartbet.co.ke/golden-race-me'
    LOGIN_URL = 'https://www.merrybet.com/rest/customer/session/login'
    COOKIES_URL = 'https://www.merrybet.com'
    BALANCE_URL = 'https://www.mozzartbet.co.ke/myBalances'

    async def login_hash(self, username: str, user_id: int, socket_id: int, cookies: Dict, http: aiohttp.ClientSession):
        pin_hash: Optional[str] = None
        while pin_hash is None:
            try:
                response = await http.get(self.HASH_URL, cookies=cookies)  # type: aiohttp.ClientResponse
                data = await response.json(content_type="application/json")  # type: Dict
                if response.status == 200:
                    pin_hash = data.get('onlineHash', None)  # type: Optional[str]
                    if isinstance(pin_hash, str):
                        return pin_hash
                    raise InvalidUserHash(username, response.status, body=data)
            except (aiohttp.ClientConnectionError, InvalidUserHash) as err:
                logger.error('(%r, username=%s, sock_id=%d) login hash %s', self, username, socket_id, str(err))
                await asyncio.sleep(30)

    async def login_password(self, username: str, password: str, http: aiohttp.ClientSession):
        unit_id: Optional[int] = None
        token: Optional[str] = None
        cookies: Optional[dict] = {}
        while unit_id is None:
            try:
                fingerprint = 'a39ad90130543e3547bf7b2bda9369'
                body = {
                    'fingerprint': fingerprint,
                    'isCasinoPage': False,
                    'password': password,
                    'username': username
                }
                response = await http.post(MozzartAuth.LOGIN_URL, json=body)  # type: aiohttp.ClientResponse
                data = await response.json(content_type="application/json")  # type: Dict
                if response.status == 200:
                    status = data.get('status', None)  # type: Optional[str]
                    if not isinstance(status, str):
                        raise InvalidUserAuthentication(username, password,
                                                        InvalidUserAuthentication.UNKNOWN_ERROR, body=data)
                    elif status == 'IVALID_CREDENTIALS':
                        raise InvalidUserAuthentication(username, password,
                                                        InvalidUserAuthentication.INVALID_CREDENTIALS, body=data)
                    user = data.get('user', {})  # type: Dict
                    unit_id = user.get('userId', None)  # type: Optional[int]
                    cookies = response.cookies.items()
                    _cookies = {}  # type: Dict
                    cookie_entry: SimpleCookie
                    for cookie_entry in cookies:
                        cookie = cookie_entry[1]  # type: Morsel
                        _cookies[cookie.key] = cookie.value
                    cookies = _cookies
                    return unit_id, token, cookies
                raise InvalidUserAuthentication(
                    username,
                    password,
                    InvalidUserAuthentication.INVALID_CREDENTIALS, body=data)
            except aiohttp.ClientConnectionError as err:
                logger.error('(%r, username=%s) login user timeout %s', self, username, err)
                await asyncio.sleep(30)

    async def sync_balance(self, username: str, token: str, cookies: Dict, http: aiohttp.ClientSession):
        user_data: Dict = {}
        while not user_data:
            try:
                body = {
                    "dontFetchOmegaBalance": True,
                    "shouldReloadOmegaBonuses": True,
                    "username": username
                }
                response = await http.post(self.BALANCE_URL, json=body,
                                           cookies=cookies)  # type: aiohttp.ClientResponse
                data = await response.json()  # type: Dict
                if response.status == 200:
                    user_data.setdefault('success', True)
                    user_data.setdefault('balance', data.get('bettingBalance'))
                    return user_data
                user_data.setdefault('success', False)
            except (aiohttp.ClientConnectionError, InvalidUserHash) as err:
                logger.error('(%r username=%s) sync balance %s', self, username, str(err))
                await asyncio.sleep(30)

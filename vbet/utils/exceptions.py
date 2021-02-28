import asyncio
from typing import Optional, Dict

# pylint: disable=super-init-not-called

class VError(Exception):
    pass


class StopApplication(VError):
    pass


class InvalidUserAuthentication(VError):
    INVALID_PASSWORD = 301
    INVALID_CREDENTIALS = 300
    UNKNOWN_ERROR = 303

    def __init__(self, username: str, password: str, code: int = 301, body=None):
        self.username: str = username
        self.password: str = password
        self.code: int = code
        self.body: Optional[Dict] = body

    def __str__(self):
        return f'Error login user {self.username} [{self.code}] {self.body}'

    def error_body(self):
        if isinstance(self.body, dict):
            self.body.setdefault('username', self.username)
        else:
            self.body = {'username': self.username, 'error': self.body}
        return self.body


class InvalidUserHash(VError):
    def __init__(self, username: str, code: int, body: Optional[dict] = None):
        self.username: str = username
        self.code: int = code
        self.body: Optional[Dict] = body

    def __str__(self):
        return f'Error getting hash {self.username} [{self.code}] {self.body}'


class InvalidUserCache(VError):
    def __init__(self, username: str):
        self.username: str = username

    def __str__(self):
        return f'User {self.username} not found in cache'


class ExpiredUserCache(VError):
    def __init__(self, username: str):
        self.username: str = username

    def __str__(self):
        return f'User {self.username} expired cache'


class InvalidEvents(VError):
    def __init__(self):
        pass

    def __str__(self):
        return 'Invalid Events'


class InvalidResults(VError):
    def __init__(self, e_block_id: int, n: int):
        self.e_block_id: int = e_block_id
        self.n: int = n

    def __repr__(self):
        return '(e_block=%d, n=%d)' % (self.e_block_id, self.n)

    def __str__(self):
        return f'{self.e_block_id} | {self.n}'


class InvalidHistory(VError):
    def __init__(self, e_block_id: int, n: int):
        self.e_block_id: int = e_block_id
        self.n: int = n

    def __repr__(self):
        return '(e_block=%d, n=%d)' % (self.e_block_id, self.n)

    def __str__(self):
        return f'{self.e_block_id} | {self.n}'


class NoResultError(ValueError):
    def __init__(self):
        pass

    def __str__(self):
        return 'No result set'


def exception_handler(loop, context):
    if 'exception' in context:
        if isinstance(context['exception'], asyncio.CancelledError):
            print(context)
        elif 'exception' not in context or not isinstance(context['exception'],
                                                          asyncio.CancelledError):
            loop.default_exception_handler(context)

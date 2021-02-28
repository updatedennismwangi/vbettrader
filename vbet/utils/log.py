"""
Custom log objects
"""


import logging
import traceback
from functools import wraps

# pylint: disable=broad-except


def exception_logger(name='error-logger'):
    def _inner(func):
        @wraps(func)
        def _wrapper(*args, **kwargs):
            _logger = logging.getLogger(f'{name}')
            try:
                return func(*args, **kwargs)
            except Exception as err:
                _logger.error('%s %s', func.__name__, traceback.format_exc())
                raise RuntimeError from err

        return _wrapper

    return _inner


def async_exception_logger(name='error-logger'):
    def _inner(func):
        @wraps(func)
        async def _wrapper(*args, **kwargs):
            _logger = logging.getLogger(f'{name}')
            try:
                return await func(*args, **kwargs)
            except Exception as err:
                _logger.error('%s %s', func.__name__, traceback.format_exc())
                raise RuntimeError from err

        return _wrapper

    return _inner


def get_logger(name):
    return logging.getLogger(name)

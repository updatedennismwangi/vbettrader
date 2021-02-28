import logging.config

from vbet.core import settings

config = {
    'version': 1,
    'disable_existing_loggers': True,
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)-8s:%(name)-12s] %(message)s',
        },
        'error-logger': {
            'format': '%(asctime)s %(filename)s [%(lineno)d ] [%(pathname)s] %(message)s'
        }
    },
    'handlers': {
        'default': {
            'level': settings.LOG_LEVEL,
            'formatter': 'standard',
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stdout',
        },
        'file': {
            'level': settings.FILE_LOG_LEVEL,
            'class': "logging.handlers.RotatingFileHandler",
            'formatter': 'standard',
            "filename": f'{settings.LOG_DIR}/vbet.log',
            "maxBytes": 100000000,
            "backupCount": 10,
        },
    },
    'loggers': {
        '': {
            'handlers': ['file', 'default'],
            'level': 'DEBUG',
            'propagate': False
        },
        'aiohttp': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': False
        },
        'websockets': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': False
        },
        'aioredis': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': False
        },
        'error-logger': {
            'handlers': ['file', 'default'],
            'level': 'DEBUG',
            'propagate': False
        }
    }
}


def setup_logger():
    logging.config.dictConfig(config)

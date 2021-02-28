import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

BETIKA = 'betika'
MOZZART = 'mozzart'
MERRYBET = 'merrybet'


BUNDESLIGA = 41047
LALIGA = 14036
PREMIER = 14045
CALCIO = 14035
KPL = 14050


PROCESS_POOL_WORKERS = 2

THREAD_POOL_WORKERS = 2

API_BACKENDS = [BETIKA, MOZZART]

DEBUG = True

LOOP_DEBUG = False

LOG_LEVEL = 'INFO'

FILE_LOG_LEVEL = 'DEBUG'

DJANGO_DEBUG = True

REDIS_URI = 'redis://localhost:6379'

REDIS_POOL_MIN = 10

REDIS_POOL_MAX = 20

DATA_DIR = f'{BASE_DIR}/data'

LOG_DIR = f'/var/log'

DUMP_DIR = f'{BASE_DIR}/data'

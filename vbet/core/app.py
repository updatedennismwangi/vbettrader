"""
Vbet [ Server application ]
"""
import argparse
from typing import List

from vbet.core import settings
from vbet.utils.parser import create_dir, decode_json

# pylint : disable=import-outside-toplevel


def parse_args(args: List):
    """
    Parse command line arguments
    :param args:
    :return:
    """
    parser = argparse.ArgumentParser()

    parser.add_argument('-d',
                        action='store_true',
                        help=f'Set the asyncio event loop debug to true or '
                             f'false.Default {settings.LOOP_DEBUG}')
    parser.add_argument('-v',
                        action='count',
                        default=1,
                        help='Set the Verbose level with highest -vv. Default'
                             ' -v')

    parser.add_argument('-p',
                        action='count',
                        default=settings.PROCESS_POOL_WORKERS,
                        help=f'Set Number of Process pool executors')

    parser.add_argument('-t',
                        action='count',
                        default=settings.THREAD_POOL_WORKERS,
                        help=f'Set Number of Thread pool executors')

    return parser.parse_args(args)


def setup(args):

    """
    Setup settings, directories and log levels
    :param args:
    """
    settings.LOOP_DEBUG = args.d
    verbose = args.v
    settings.THREAD_POOL_WORKERS = args.t
    settings.PROCESS_POOL_WORKERS = args.p

    if verbose == 0:
        settings.LOG_LEVEL = 'INFO'
        settings.FILE_LOG_LEVEL = 'INFO'
    elif verbose == 1:
        settings.LOG_LEVEL = 'INFO'
        settings.FILE_LOG_LEVEL = 'DEBUG'
    else:
        settings.LOG_LEVEL = 'DEBUG'
        settings.FILE_LOG_LEVEL = 'DEBUG'

    create_dir(settings.LOG_DIR)
    create_dir(settings.DATA_DIR)
    create_dir(settings.DUMP_DIR)


def application(args: List) -> int:
    """
    Main application
    :param args:
    :return: exit_code
    """
    # Configure settings
    args = parse_args(args)
    setup(args)
    # Logging setup
    from vbet.utils.logger import setup_logger
    setup_logger()

    with open(settings.DATA_DIR+"/vweb.json") as f:
        config = decode_json(f.read())

    # Main Application
    from vbet.core.vbet import Vbet
    app = Vbet()
    return app.run()

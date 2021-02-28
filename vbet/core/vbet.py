import asyncio
import traceback
import signal
from typing import Dict, Optional

import vbet
from vbet.core import settings
from vbet.core.provider import Provider
from vbet.utils import exceptions
from vbet.utils.log import get_logger

logger = get_logger('vbet')

EXIT_SUCCESS = 100
EXIT_INTERRUPT = 101

# pylint : disable=import-outside-toplevel,unused-import


class Vbet:
    exit_code: int = 0
    exit_flag: bool = False
    loop: Optional[asyncio.AbstractEventLoop] = None
    providers: Dict[str, Provider] = {}

    def run(self) -> int:
        logger.info('Vbet Server build %s', vbet.__version__)

        try:
            # Setup event loop, loglevel and default exception handler
            self.loop = asyncio.get_event_loop()
            self.loop.add_signal_handler(signal.SIGTERM, self.sig_term_callback)
            self.loop.set_debug(settings.LOOP_DEBUG)
            self.loop.set_exception_handler(exceptions.exception_handler)

            # Django orm
            logger.info('Setting up webservice')
            from vbet.core import vclient
            from vweb.vclient.models import ProviderInstalled, LiveSession, Tickets
            from vweb.vclient.models import User as UserAdmin, Providers as _Providers
            Provider.TicketsDb = Tickets
            Provider.UserDb = UserAdmin
            Provider.ProvidersDb = _Providers
            Provider.LiveSessionDb = LiveSession
            Provider.ProviderInstalledDb = ProviderInstalled

            # Install providers from settings
            self.loop.run_until_complete(self.setup_providers())
            # Server forever until Ctrl + C then run shutdown and schedule
            # clean_up and later call clean_up_callback to stop the loop.

            try:
                logger.info('Server online. Press Ctrl + C to terminate')
                self.loop.run_forever()
            except KeyboardInterrupt:
                # Start shutdown sequence
                self.shutdown()

        except (KeyboardInterrupt, ModuleNotFoundError, Exception):
            # Handle errors during setup and during shutdown
            logger.critical('Application error %s', traceback.format_exc())
            self.exit_code = EXIT_INTERRUPT
        finally:
            self.loop.close()
            logger.info('Terminated application : %d', self.exit_code)
            return self.exit_code

    async def setup_providers(self):
        # Load all providers configured in the settings file from the database
        from vbet.core.orm import load_provider_data
        for provider_id in settings.API_BACKENDS:
            config = await load_provider_data(provider_id)
            if config:
                for x in range(3):
                    provider = Provider(provider_id, x)
                    self.providers[provider_id] = provider
                    provider.start()

    def shutdown(self):
        # Schedule clean up coroutine and save user states
        logger.info('Graceful shutdown')
        future = self.loop.create_task(self.clean_up())
        future.add_done_callback(self.clean_up_callback)

        # Run the loop until the exit_flag has been set when all providers close
        # and all resources are free.
        while True:
            self.loop.run_forever()
            if self.exit_flag:
                break
        logger.info('Graceful Shutdown complete')

    async def clean_up(self):
        # Cleanup all providers
        logger.info("Clean up")
        for provider in self.providers.values():
            provider.join()

    def clean_up_callback(self, future: asyncio.Task):
        # Log any errors in the clean_up coroutine and stop event loop
        if future.exception():
            logger.exception('Error shutting down %s', future.exception())
        self.exit_flag = True
        self.exit_code = EXIT_SUCCESS
        self.loop.stop()

    @staticmethod
    def sig_term_callback():
        # Trigger clean shutdown
        raise KeyboardInterrupt

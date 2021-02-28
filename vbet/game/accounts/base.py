from abc import abstractmethod
from typing import Dict, Optional, Union

from .manager import AccountManager
from ..tickets import Ticket


class Account:
    demo = False
    manager: AccountManager

    def __init__(self):
        self.credit = 0
        self.won_amount = 0
        self.lost_amount = 0
        self.initial_token = 1
        self.profit_token = 0
        self.max_stake = 100000

    def set_manager(self, manager: AccountManager):
        self.manager = manager

    def setup(self, config: Dict):
        self.initial_token = config.get('initial_token', 5)
        self.profit_token = config.get('profit', 1)

    async def on_win(self, ticket: Ticket):
        await self.manager.on_win(ticket)
        self.won_amount += ticket.total_won

    async def on_loose(self, ticket: Ticket):
        await self.manager.on_loose(ticket)
        self.lost_amount += (ticket.total_won - ticket.stake)

    def normalize_stake(self, amount: float):
        return self.manager.normalize_amount(amount)

    @abstractmethod
    async def get_stake(self, odd_value: Optional[float] = None):
        raise NotImplementedError('Implement get stake')


class LiveAccount(Account):
    async def get_stake(self, odd_value: Optional[float] = None):
        pass

    def borrow(self, amount: float):
        pass


class DemoAccount(Account):
    demo = True

    def __init__(self):
        super().__init__()
        self.credit = 100000

    async def get_stake(self, odd_value: Optional[float] = None):
        pass

    async def borrow(self, amount):
        await self.manager.borrow(amount)


class SessionAccount:
    manager: AccountManager
    account: Union[LiveAccount, DemoAccount]
    account_id = 0
    demo: bool

    def __init__(self, manager: AccountManager, demo: bool):
        self.manager = manager
        self.demo = demo
        if self.demo:
            self.account: DemoAccount = DemoAccount()
        else:
            self.account: LiveAccount = LiveAccount()
        self.account.set_manager(manager)

    async def get_stake(self, **kwargs) -> float:
        pass

    async def on_win(self, ticket: Ticket):
        await self.account.on_win(ticket)

    async def on_loose(self, ticket: Ticket):
        await self.account.on_loose(ticket)

    def setup(self, config: Dict):
        self.account.setup(config)

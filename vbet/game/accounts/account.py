from typing import Dict

from .base import SessionAccount
from .manager import AccountManager
from ..tickets import Ticket


class RecoverAccount(SessionAccount):
    account_id: int = 1
    name = "Martingale"

    def __init__(self, manager: AccountManager, demo: bool):
        super().__init__(manager, demo)
        self.amount_lost: float = 0
        self.max_stake: float = 5000
        self.max_stake_lost: float = 70000
        self.initial_token = 0

    async def get_stake(self, **kwargs) -> float:
        odd = float(kwargs.get('odd_value'))
        stake = self.amount_lost / (odd - 1)
        if stake > self.max_stake or (stake + self.amount_lost) > self.max_stake_lost:
            self.amount_lost = self.initial_token
            stake = self.amount_lost / (odd - 1)
        return self.manager.normalize_amount(stake)

    async def on_win(self, ticket: Ticket):
        await super().on_win(ticket)
        self.amount_lost = self.initial_token

    async def on_loose(self, ticket: Ticket):
        await super().on_loose(ticket)
        self.amount_lost += (ticket.stake + self.account.profit_token)

    def setup(self, config: Dict):
        self.initial_token = config.get('initial_token', 20)
        self.amount_lost = self.initial_token


class FixedStake(SessionAccount):
    account_id: int = 2
    stake: float
    name = "Fixed Stake"

    async def get_stake(self, **kwargs) -> float:
        return self.manager.normalize_amount(self.stake)

    def setup(self, config: Dict):
        self.stake: float = config.get('stake')


class FixedProfitAccount(SessionAccount):
    account_id: int = 3
    profit: float
    name = "Fixed Profit"

    async def get_stake(self, **kwargs) -> float:
        odd_value = kwargs.get('odd_value')
        return self.manager.normalize_amount(round(self.profit / (odd_value - 1), 2))

    def setup(self, config: Dict):
        self.profit = config.get('profit')


class FixedReturnAccount(SessionAccount):
    account_id: int = 4
    profit: float
    name = "Fixed Return"

    async def get_stake(self, **kwargs) -> float:
        odd_value = kwargs.get('odd_value')
        return self.manager.normalize_amount(round(self.profit / odd_value, 2))

    def setup(self, config: Dict):
        self.profit = config.get('profit')


class FixedPercentAccount(SessionAccount):
    account_id: int = 5
    value: float
    name = "Fixed Percent"

    async def get_stake(self, **kwargs) -> float:
        return round(await self.manager.credit * (self.value / 100), 2)

    def setup(self, config: Dict):
        self.value = config.get('percent_value')

from __future__ import annotations

import asyncio
from typing import List, TYPE_CHECKING

from ..tickets import Ticket

if TYPE_CHECKING:
    from ..user import User


class AccountManager:
    MIN_BET_AMOUNT = 5
    profit: int
    _lost_amount: int
    _won_amount: int

    def __init__(self, user: User):
        self.user: User = user
        self.setup(0)
        self._credit: float = 0
        self._demo_credit: float = 100000
        self._lost_amount = 0
        self._won_amount = 0
        self.credit_lock: asyncio.Lock = asyncio.Lock()
        self.lost_lock: asyncio.Lock = asyncio.Lock()
        self.won_lock: asyncio.Lock = asyncio.Lock()
        self._bonus_level: int = 0
        self.bonus_mode: bool = False
        self.bonus_total: float = 0
        self._jackpot_amount: float = 25
        self._levels: List[float] = [100, 250, 500, 1000, 5000, 25000]
        self._total_stake: float = 0
        self.initialized: bool = False

    async def initialize(self):
        self.initialized = True

    @property
    def total_stake(self):
        return self._total_stake

    @total_stake.setter
    def total_stake(self, stake: float):
        self._total_stake += stake

    @property
    def bonus_level(self):
        return self._bonus_level

    @bonus_level.setter
    def bonus_level(self, level: int):
        if level is None:
            level = -1
        self._bonus_level = level

    @property
    def jackpot_amount(self):
        return self._jackpot_amount

    @property
    def jackpot_value(self):
        if self._bonus_level > -1:
            top_limit = self._levels[self.bonus_level]
            return round((self.jackpot_amount / top_limit) * 100, 2)
        return 0

    @jackpot_amount.setter
    def jackpot_amount(self, amount):
        self._jackpot_amount = float(amount)

    def is_bonus_ready(self) -> bool:
        if self.bonus_mode:
            if self.total_stake >= self.bonus_total:
                return True
        else:
            if self._bonus_level == 5:
                bonus_amount = self._levels[-1]
                a = (self._jackpot_amount / bonus_amount) * 100
                return a >= 99.3
        return False

    def setup(self, credit: float):
        self._credit = credit
        self.profit = 0
        self._lost_amount = 0

    @property
    async def credit(self):
        async with self.credit_lock:
            return self._credit

    @property
    async def demo_credit(self):
        return self._demo_credit

    async def update(self, credit: float):
        async with self.credit_lock:
            self._credit = credit

    async def fund(self, credit: float):
        async with self.credit_lock:
            self._credit += credit

    async def on_win(self, ticket: Ticket):
        async with self.won_lock:
            self._won_amount += ticket.total_won
        if ticket.demo:
            self._demo_credit += ticket.total_won

    async def on_loose(self, ticket: Ticket):
        async with self.lost_lock:
            self._lost_amount += ticket.stake

    async def borrow(self, amount: float):
        self._demo_credit -= amount

    def normalize_amount(self, amount) -> float:
        game_settings = self.user.settings.game_settings.get('GL')
        if game_settings:
            min_stake = game_settings.get('min_stake', 0)
            max_stake = game_settings.get('max_stake', 0)
            if amount < min_stake:
                amount = min_stake
            if amount > max_stake:
                amount = max_stake
        if amount < self.MIN_BET_AMOUNT:
            amount = self.MIN_BET_AMOUNT
        return round(amount, 2)

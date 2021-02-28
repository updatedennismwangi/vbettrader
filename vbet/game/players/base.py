from __future__ import annotations

import asyncio
from typing import Any, List, Tuple, TYPE_CHECKING, Dict

from vbet.core.mixin import StatusMap
from vbet.game.markets import Markets
from vbet.game.tickets import Ticket
from vbet.utils.log import get_logger

if TYPE_CHECKING:
    from vbet.game.competition import LeagueCompetition
    from vbet.game.session import LiveSession

NAME = 'player'

logger = get_logger('player')


class Player(StatusMap):
    live_session: LiveSession
    competitions: List[LeagueCompetition]
    mode: str

    status: str
    closing: bool
    name: str
    bet_ready: bool
    jackpot_ready: bool
    _forecast: bool
    shutdown_event: asyncio.Event
    options: Dict
    compat_competitions: Dict
    future_weeks: List[int]
    is_random: bool
    game_map: Dict[int, bool]

    def __init__(self, name: str = None, **kwargs):
        self.live_session = kwargs.get('live_session')
        self.status = self.INACTIVE
        self.closing = False
        self.name = name if name else NAME
        self.bet_ready = False
        self.jackpot_ready = False
        self._forecast = True
        self.shutdown_event = asyncio.Event()
        self.shutdown_event.set()
        self.competition_map = {}
        self.options = {}
        self.game_map = {key: True for key in self.live_session.competitions.keys()}
        self.required_map = {key: [] for key in self.live_session.competitions.keys()}

    def __str__(self):
        return self.name

    def __repr__(self):
        return '[%s]' % self.name

    def start(self):
        self.status = self.RUNNING
        # logger.debug(f'[{self.competition.user.username}:{self.competition.competition_id}] {self.name} Activated')

    def required_weeks(self, competition_id) -> List[int]:
        return self.required_map.get(competition_id)

    async def on_event(self, competition_id: int, week: int) -> List[Ticket]:
        # competition = self.live_session.user.get_competition(competition_id)
        tickets = []  # type: List[Ticket]
        if self.can_forecast(competition_id):
            tickets = await self.forecast(competition_id, week)
        return tickets

    async def on_result(self, competition_id: int):
        pass

    async def on_ticket(self, ticket: Ticket):
        stake = ticket.stake
        if ticket.total_won < stake:
            await self.live_session.account.on_loose(ticket)
        else:
            await self.live_session.account.on_win(ticket)
        await self.on_ticket_resolve(ticket)

    async def on_ticket_resolve(self, ticket: Ticket):
        pass

    async def on_new_league(self, competition_id: int):
        pass

    async def forecast(self, competition_id: int, week: int) -> List[Ticket]:
        return []

    async def wss_login_data(self):
        return {
            'status': self.status,
            'playerId': self.name,
        }

    def can_forecast(self, competition_id) -> bool:
        return self.game_map.get(competition_id, True)

    def setup_jackpot(self):
        self.jackpot_ready = True

    def clear_jackpot(self):
        self.jackpot_ready = False

    @staticmethod
    def get_result_ratio(last_result: List[str]) -> Tuple[int, int]:
        home_result = []
        away_result = []
        home_ratio = 0
        away_ratio = 0
        for result in last_result:
            home = result[0]
            away = result[1]
            if home == "W":
                home_result.append(3)
                home_ratio += 20
            elif home == "D":
                home_result.append(1)
            else:
                home_result.append(0)
            if away == "W":
                away_result.append(3)
                away_ratio += 20
            elif away == "D":
                away_result.append(1)
            else:
                away_result.append(0)
        return home_ratio, away_ratio

    @staticmethod
    def pick_winner(head_to_head: List[List[str]], draw=False) -> Tuple[Any, Any]:
        a = 0
        b = 0
        c = 0
        if len(head_to_head) >= 5:
            for result in head_to_head:
                home_goals = int(result[0])
                away_goals = int(result[1])
                if home_goals > away_goals:
                    a += 1
                elif home_goals < away_goals:
                    b += 1
                else:
                    c += 1
            if draw:
                a += c
                b += c
            if a > b:
                return 0, a
            if b > a:
                return 1, b
            return 2, a
        return None, None

    @staticmethod
    def pick_over(over, head_to_head: List[List[str]]):
        a = 0
        if len(head_to_head) >= 5:
            for result in head_to_head:
                home_goals = int(result[0])
                away_goals = int(result[1])
                if (home_goals + away_goals) > over:
                    a += 1
                else:
                    a -= 1
            return a
        return None

    @staticmethod
    def get_market_info(market: str) -> Tuple[Any, Any, Any]:
        for market_type, market_data in Markets.items():
            if market in market_data:
                data = market_data.get(market)
                if data:
                    return market_type, data.get('name'), int(data.get('key'))
        return None, None, None

    @staticmethod
    def get_market(market: str, odds: List[float]):
        market_id, odd_name, odd_index = Player.get_market_info(market)
        if market_id:
            return float(odds[odd_index])
        return -1

    @staticmethod
    def is_sublist(a, b):
        if len(a) > len(b):
            return False
        for i in range(0, len(b) - len(a) + 1):
            if b[i:i + len(a)] == a:
                return i
        return -1

    @staticmethod
    def points_lost(a, b, c, m=5):
        for i in range(0, len(b) - c + 1):
            t = b[i:i + c]  # type: List
            u = list(filter('x'.__ne__, t))
            if sum(u) < a:
                if len(u) == m:
                    return i
        return -1

    def get_required_weeks(self, competition_id: int):
        required_weeks = self.required_map.get(competition_id, {})
        required_weeks.clear()
        required_weeks.extend(range(15, 30, 2))
        # required_weeks.extend(range(1, 15))
        # required_weeks.extend(range(16, 30, 2))
        # required_weeks.extend(range(30, 39))

    async def exit(self):
        await self.shutdown_event.wait()

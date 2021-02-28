from __future__ import annotations

import asyncio
import inspect
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING, Type

from vbet.core.mixin import StatusMap
from vbet.game.accounts import account
from vbet.game.accounts.base import SessionAccount
from vbet.utils.log import get_logger
from . import players
from ..core.orm import on_start_live_session

if TYPE_CHECKING:
    from .user import User
    from .tickets import Ticket
    from .players.base import Player
    from vweb.vclient.models import LiveSession as DbLiveSession

logger = get_logger('session')


class LiveSession(StatusMap):
    user: User
    event_lock: asyncio.Lock
    play_events: Dict[int, asyncio.Event]
    status: str
    demo: bool
    account: SessionAccount
    session_id: int
    won: int
    stake: int
    competitions: Dict
    player: Optional[Player]
    db_live_session: DbLiveSession
    ticket_maps: Dict[int, Dict[int, bool]]
    target_amount: int

    def __init__(self, user: User, db_live_session: DbLiveSession, competitions: Dict, account_data: Dict):
        self.user = user
        self.demo = account_data.setdefault('demo', True)
        self.event_lock = asyncio.Lock()
        self.ticket_maps = {}
        self.status = self.INACTIVE
        self.db_live_session = db_live_session
        self.session_id = db_live_session.session_id
        self.competitions = {}
        for competition_id in competitions:
            self.add_competition(int(competition_id))
            self.ticket_maps[competition_id] = {}
        self.play_events = {}
        for competition_id in competitions:
            self.play_events[competition_id] = asyncio.Event()
        self.player = None
        self.stake = 0
        self.won = 0
        self.target_amount = account_data.get('target_amount')
        self.setup_account(account_data)

    def set_player(self, player_name: str):
        mod = getattr(players, player_name)
        cls = getattr(mod, player_name.capitalize())  # type: Type[Player]
        self.player = cls(live_session=self)
        self.player.start()

    def setup_account(self, account_data: Dict):
        target_account_id = account_data.get('account_id')
        options = account_data.get('options')
        for name, obj in inspect.getmembers(account):
            if inspect.isclass(obj):
                account_id = getattr(obj, 'account_id', None)
                account_name = getattr(obj, 'name', None)
                if account_id or account_name:
                    if account_id == target_account_id or account_name == target_account_id:
                        self.account = obj(self.user.account_manager, self.demo)
                        self.account.setup(options)
                        break

    def add_competition(self, competition_id: int):
        self.competitions[competition_id] = {}

    def start(self):
        if self.status != self.RUNNING:
            self.status = self.RUNNING
            asyncio.ensure_future(on_start_live_session(self.db_live_session))
            for competition_id in self.competitions:
                competition = self.user.get_competition(competition_id)
                if competition.status != competition.RUNNING:
                    competition.wait_event = False
                    asyncio.ensure_future(competition.start())

    def stop(self):
        self.status = self.SLEEPING
        for competition_id in self.competitions:
            competition = self.user.get_competition(competition_id)
            if competition:
                try:
                    competition.sessions.remove(self.session_id)
                except ValueError:
                    pass
                else:
                    if not competition.sessions:
                        competition.status = competition.SLEEPING

    async def on_events(self, competition_id: int, week: int) -> Tuple[asyncio.Event, List[Ticket]]:
        await self.event_lock.acquire()
        # print(f"Acquiring lock {self.session_id} {competition_id}")
        self.ticket_maps.get(competition_id).clear()
        tickets = await self.player.on_event(competition_id, week)
        self.play_events[competition_id] = asyncio.Event()
        if not tickets:
            self.play_events.get(competition_id).set()
            # print(f"Releasing lock {self.session_id} {competition_id}")
            self.event_lock.release()
        for ticket in tickets:
            ticket.live_session_id = self.session_id
            ticket.db_live_session = self.db_live_session
            ticket.demo = self.demo
        return self.play_events.get(competition_id), tickets

    async def on_new_league(self, competition_id: int):
        await self.player.on_new_league(competition_id)

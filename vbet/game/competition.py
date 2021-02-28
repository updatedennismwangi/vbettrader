from __future__ import annotations

import asyncio
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple, TYPE_CHECKING

from vbet.core.mixin import StatusMap
from vbet.core import settings
from vbet.utils import exceptions
from vbet.utils.log import get_logger
from vbet.utils.parser import Resource, dump_data
from vbet.utils.parser import map_resource_to_name
from . import players
from .markets import Markets
from .session import LiveSession
from .table import LeagueTable
from .tickets import Ticket

if TYPE_CHECKING:
    from vbet.game.user import User

# pylint : disable=raise-missing-from

logger = get_logger('competition')
account_logger = get_logger('account')


class BaseCompetition(StatusMap):
    user: User
    status: str
    competition_id: int
    configured: bool
    sessions: List[int]
    socket: int

    def __init__(self, user: User, competition_id: int):
        self.user = user
        self.competition_id = competition_id
        self.configured = False
        self.status = self.OFFLINE
        self.sessions = []
        self.socket = 0


class LeagueCompetition(BaseCompetition):
    # Mode
    SCHEDULED = 'SCHEDULED'
    ON_DEMAND = 'ON_DEMAND'

    # Competition phase
    SLEEPING = 'SLEEPING'
    EVENTS = 'EVENTS'
    EVENTS_STATS = 'EVENTS_STATS'
    TICKETS = 'TICKETS'
    HISTORY = 'HISTORY'
    FUTURE = 'FUTURE'
    RESULT_TICKETS = 'RESULT_TICKETS'
    FUTURE_RESULT = 'FUTURE_RESULT'
    RESULTS = 'RESULTS'
    DISPATCH = 'DISPATCH'
    PLAYING = 'PLAYING'
    EVENT_WAIT = 'EVENT_WAIT'

    countdown: Optional[float]
    offset: Optional[float]
    mode: str
    max_week: int
    event_time: Optional[float]
    e_block_id: Optional[int]
    league: Optional[int]
    week: Optional[int]
    table: LeagueTable
    phase: str
    caching: bool
    restoring: bool
    caching_future: bool
    cache_enabled: bool
    cached: bool
    caching_single: bool
    future_results: bool
    fetching_future: bool
    auto_skip: bool
    last_history_block: Optional[int]
    last_history_n: Optional[int]
    last_result_block: Optional[int]
    last_result_n: Optional[int]

    required_weeks: List[int]
    event_time_enabled: bool
    event_time_interval: int
    profile: str = 'MOBILE'
    result_future: Optional[asyncio.Task]
    team_labels: Dict[int, str]
    team_ids: Dict[str, int]
    active_tickets: List[int]
    session_events: Dict[int, asyncio.Event]
    blocks: Dict[int, int]
    result_blocks: List[int]
    league_games: Dict[int, Dict]
    socket_closed: bool
    jackpot_ready: bool
    max_previous_block: Optional[int]
    max_future_block: Optional[int]
    future_block_count: int
    previous_block_count: int
    wait_event: bool

    def __init__(self, user: User, competition_id: int, mode: str, participants: List[Dict]):
        super().__init__(user, competition_id)
        game_config = self.user.settings.playlists.get(self.competition_id)
        if not game_config:
            self.countdown = 0
            self.offset = 0
        else:
            self.countdown = game_config.get('countdown')
            self.offset = game_config.get('offset')
        self.mode = mode
        self.team_labels = {}
        self.setup_participants(participants)
        self.event_time = None
        self.e_block_id = None
        self.league = None
        self.week = None
        self.max_future_block = None
        self.max_previous_block = None
        self.future_block_count = 0
        self.previous_block_count = 0
        self.last_result_n = 0
        self.last_result_block = 0
        self.last_history_n = 0
        self.last_history_block = 0
        self.table = LeagueTable(self.max_week)
        self.phase = self.SLEEPING
        self.restoring = False
        self.caching = False
        self.caching_future = False
        self.cache_enabled = True
        self.cached = False
        self.caching_single = False
        self.future_results = True
        self.fetching_future = False
        self.auto_skip = False

        self.required_weeks = []
        self.event_time_enabled = True
        self.event_time_interval = 0.2
        self.result_event = asyncio.Event()
        self.wait_event = False
        self.result_future = None
        self.team_ids = {}
        self.active_tickets = []
        self.blocks = {}
        self.session_events = {}
        self.result_blocks = []
        self.league_games = {}
        self.socket_closed = False
        self.jackpot_ready = False

    def __repr__(self):
        return '[%s:%d]' % (self.user.username, self.competition_id)

    def init(self):
        logger.info('%r Competition installed', self)

    async def start(self):
        self.status = self.RUNNING
        self.phase = self.EVENTS
        await self.next_block_event()

    async def resume(self):
        logger.debug('%r Resumed with phase: %s', self, self.phase)
        if self.phase == self.EVENTS or self.phase == self.EVENTS_STATS:
            await self.next_block_event()
        elif self.phase == self.RESULTS or self.phase == self.RESULT_TICKETS:
            await self.fetch_result(self.result_blocks[0], 1)
        elif self.phase == self.HISTORY:
            await self.fetch_history(self.last_history_block, self.last_history_n)
        elif self.phase == self.FUTURE:
            await self.fetch_history(self.last_history_block, self.last_history_n)
        elif self.phase == self.FUTURE_RESULT:
            not_ready = self.table.check_weeks(self.required_weeks)
            if not_ready:
                await self.get_future_weeks(not_ready)
        elif self.phase == self.TICKETS:
            logger.debug('%r Competition resume success. Events : %s', self,
                         str(self.result_blocks))
        else:
            logger.warning('%r Resumed with phase: %s', self, self.phase)

    def setup_participants(self, participants: List[Dict]):
        self.team_labels.clear()
        for team_data in participants:
            self.team_labels[int(team_data.get('id'))] = team_data.get('fifaCode')
        self.team_ids = {v: k for k, v in self.team_labels.items()}
        self.max_week = (len(self.team_labels) - 1) * 2

    def register_session(self, session: LiveSession):
        self.sessions.append(session.session_id)

    # Resources
    def resource_events(self, options: Dict) -> Dict:
        event_time = self.get_event_time() if self.mode == self.SCHEDULED else None
        countdown = self.countdown if self.mode == self.SCHEDULED else None
        offset = self.offset if self.mode == self.SCHEDULED else None
        return {
            'contentType': "PLAYLIST",
            'contentId': self.competition_id,
            'countDown': countdown,
            'offset': offset,
            'eventTime': event_time,
            'n': options.get('n'),
            'profile': self.profile,
            'oddSettingId': self.user.settings.odd_settings_id,
            'unitId': self.user.settings.unit_id
        }

    def resource_results(self, options: Dict) -> Dict:
        countdown = self.countdown if self.mode == self.SCHEDULED else None
        offset = self.offset if self.mode == self.SCHEDULED else None
        data = {
            'contentType': "PLAYLIST",
            'contentId': self.competition_id,
            'countDown': countdown,
            'offset': offset,
            'profile': self.profile,
            'oddSettingId': self.user.settings.odd_settings_id,
            'unitId': self.user.settings.unit_id
        }
        if self.mode == self.SCHEDULED:
            event_time = self.event_time
        else:
            event_time = None
            data.setdefault('eBlockId', options.get('e_block_id'))
        data.setdefault('n', options.get('n'))
        data.setdefault('eventTime', event_time)
        return data

    def resource_stats(self, options: Dict) -> Dict:
        event_time = self.get_event_time() if self.mode == self.SCHEDULED else None
        countdown = self.countdown if self.mode == self.SCHEDULED else None
        offset = self.offset if self.mode == self.SCHEDULED else None
        return {
            'contentType': "PLAYLIST",
            'contentId': self.competition_id,
            'countDown': countdown,
            'offset': offset,
            'eBlockId': options.get('e_block_id'),
            'eventTime': event_time,
            'n': options.get('n'),
            'profile': self.profile,
            'oddSettingId': self.user.settings.odd_settings_id,
            'unitId': self.user.settings.unit_id
        }

    def resource_history(self, options: Dict) -> Dict:
        return {
            'contentType': "PLAYLIST",
            'contentId': self.competition_id,
            'countDown': None,
            'offset': None,
            'n': options.get('n'),
            'eBlockId': options.get('e_block_id'),
            'profile': self.profile,
            'oddSettingId': self.user.settings.odd_settings_id,
            'unitId': self.user.settings.unit_id
        }

    async def fetch_event(self, n: int):
        options = dict()
        options.setdefault('n', n)
        payload = self.resource_events(options)
        self.send(Resource.EVENTS, payload)

    async def fetch_result(self, e_block_id: int, n: int):
        self.last_result_block = e_block_id
        self.last_result_n = n
        options = dict()
        options.setdefault('e_block_id', e_block_id)
        options.setdefault('n', n)
        payload = self.resource_results(options)
        self.send(Resource.RESULTS, payload)

    async def fetch_history(self, e_block_id: int, n: int):
        self.last_history_block = e_block_id
        self.last_history_n = n
        options = dict()
        options.setdefault('e_block_id', e_block_id)
        options.setdefault('n', n)
        payload = self.resource_history(options)
        self.send(Resource.HISTORY, payload)

    async def fetch_stats(self, e_block_id: int, n: int):
        options = dict()
        options.setdefault('e_block_id', e_block_id)
        options.setdefault('n', n)
        payload = self.resource_stats(options)
        self.send(Resource.STATS, payload)

    # Event blocks
    async def next_block_result(self, e_block_id: int, block: int = 1):
        await self.await_event_time()
        await self.fetch_result(e_block_id, block)

    async def next_block_event(self, block: int = 1):
        await self.fetch_event(block)

    async def get_block_result(self, e_block_id: int, events: Dict[int, asyncio.Event]):
        await asyncio.wait([event.wait() for event in events.values()], return_when=asyncio.ALL_COMPLETED)
        await self.fetch_result(e_block_id, 1)

    async def get_blocks_result(self):
        await asyncio.wait([event.wait() for event in self.session_events.values()], return_when=asyncio.ALL_COMPLETED)
        self.phase = self.RESULT_TICKETS
        await self.fetch_result(self.result_blocks[0], 1)

    # Resources callbacks
    async def events_callback(self, valid_response: bool, body: Any):
        try:
            if valid_response and isinstance(body, list):
                try:
                    data = body[0]
                    if not isinstance(data, dict):
                        raise exceptions.InvalidEvents()
                except IndexError as exc:
                    raise exceptions.InvalidEvents() from exc
                else:
                    await self.resource_events_process(data)
            else:
                raise exceptions.InvalidEvents()
        except exceptions.InvalidEvents as err:
            logger.warning('%r Invalid Events Block', self)
            await asyncio.sleep(2)
            await self.fetch_event(1)

    async def results_callback(self, valid_response: bool, body: Any):
        try:
            if valid_response and isinstance(body, list):
                try:
                    data = body[0]
                    if not isinstance(data, dict):
                        raise ValueError
                except (ValueError, IndexError):
                    raise exceptions.InvalidResults(self.last_result_block, self.last_result_n)
                else:
                    try:
                        await self.resource_result_process(data)
                    except exceptions.NoResultError:
                        raise exceptions.InvalidResults(self.last_result_block, self.last_result_n)
            else:
                raise exceptions.InvalidResults(self.last_result_block, self.last_result_n)
        except exceptions.InvalidResults as err:
            logger.warning('%r Invalid Result Block: League: %d', self, self.league)
            await asyncio.sleep(3)
            await self.fetch_result(err.e_block_id, err.n)

    async def history_callback(self, valid_response: bool, body: Any):
        try:
            if valid_response and isinstance(body, list):
                await self.resource_history_process(body)
            else:
                raise exceptions.InvalidHistory(self.last_history_block, self.last_history_n)

        except exceptions.InvalidHistory as err:
            logger.warning('%r Invalid History Block: %r League: %d', self, err, self.league)
            await asyncio.sleep(3)
            await self.fetch_history(err.e_block_id, err.n)

    async def resource_history_process(self, data: List[Dict]):
        e_blocks = []
        for week_result in data:
            events = week_result.get('events')
            e_block_id = week_result.get('eBlockId')
            event_data = week_result.get('data', {})
            league = event_data.get('leagueId')
            week = event_data.get('matchDay')
            if league != self.league:
                continue
            e_blocks.append(e_block_id)
            logger.debug('%r History Block: %d League: %d Week: %d', self, e_block_id, league, week)
            self.blocks[e_block_id] = week
            results = {}
            matches = {}
            winning_ids = {}
            result_ids = {}
            for event_index, event in enumerate(events):
                data = event.get('data')
                participants = data.get('participants')
                player_a = participants[0]
                player_b = participants[1]
                team_a = player_a.get('fifaCode')
                team_b = player_b.get('fifaCode')
                event_id = event.get('eventId')
                result = event.get('result')
                odds = []  # type: List[float]
                odd_values = data.get('oddValues')  # type: List[str]
                for odd in odd_values:
                    odds.append(float(odd))
                matches[event_id] = {'A': team_a, 'B': team_b, 'odds': odds, 'index': event_index,
                                     'participants': participants}
                if result:
                    won = result.get('wonMarkets')
                    result_data = result.get('data')
                    half_lost = result_data.get('halfLostMarkets')
                    half_won = result_data.get('halfWonMarkets')
                    refund_stake = result_data.get('refundMarkets')
                    handicap_data = {'half_lost': half_lost, 'half_won': half_won, 'refund_stake': refund_stake}
                    x = set(won)
                    y = set(str(_) for _ in range(15, 43))
                    r = list(x & y)
                    z = r[0]
                    score = Markets['Correct_Score'][z]['name'].split('_')
                    results[event_id] = {
                        'id': event_id, 'A': team_a, 'B': team_b,
                        'score': (int(score[1]),
                                  int(score[2]))}
                    result_ids[event_id] = [int(_) for _ in won]
                    winning_ids[event_id] = handicap_data
            self.league_games[week] = matches

            if self.caching:
                self.table.feed_result(e_block_id, league, week, results, result_ids, winning_ids)
        if self.caching:
            self.previous_block_count += 1
            if self.previous_block_count < self.max_previous_block:
                await self.fetch_history(e_blocks[-1], -10)
            elif self.future_block_count < self.max_future_block:
                self.caching_future = True
                self.phase = self.FUTURE    # Future phase
                self.caching = False
                logger.debug('%r %r Caching league %d', self, self.user, self.league)
                # await asyncio.sleep(0.5)  # sleep
                await self.fetch_history(self.e_block_id, 10)
            else:
                self.cached = True
                self.caching = False

                logger.debug('%r %r All events cached %d', self, self.user, self.league)
                self.required_weeks = self.get_required_weeks()
                await self.dispatch_events()
        else:
            if self.caching_future:
                self.future_block_count += 1
                if self.future_block_count < self.max_future_block:
                    if e_blocks:
                        await self.fetch_history(e_blocks[-1] + 1, 10)
                        return
                self.caching_future = False
                self.cached = True

                logger.debug('%r %r All events cached %d', self, self.user, self.league)
                self.required_weeks = self.get_required_weeks()
                await self.dispatch_events()

    async def resource_events_process(self, data: Dict):
        e_block_id = data.get('eBlockId')
        event_data = data.get('data')
        if isinstance(e_block_id, int):
            event_data.setdefault('competitionId', self.competition_id)
            league = event_data.get('leagueId')
            match_day = event_data.get('matchDay')
            if league != self.league:
                self.reset_league(league)   # Reset league
                for live_session_id in self.sessions:
                    live_session = self.user.get_live_session(live_session_id)
                    await live_session.on_new_league(self.competition_id)
                # Disable auto skip if running
                if match_day == 1:
                    self.auto_skip = False

            if self.phase == self.EVENTS:
                self.reset_blocks(match_day)
                self.week = match_day
                self.e_block_id = e_block_id

                logger.debug('%r Event Block: %d League: %d Week: %d', self, self.e_block_id, self.league, self.week)
                if self.max_previous_block:
                    self.phase = self.HISTORY   # History phase
                    self.caching = True
                    await self.fetch_history(e_block_id, -10)
                else:
                    logger.debug('%r %r Caching league %d', self, self.user, self.league)
                    self.phase = self.FUTURE    # Future phase
                    self.caching_future = True
                    await self.fetch_history(e_block_id, 10)
            elif self.phase == self.EVENTS_STATS:
                events = data.get('events')
                stats = {}
                for event in events:
                    event_id = event.get('eventId')
                    _data = event.get('data')
                    _stats = _data.get('stats')
                    stats[event_id] = _stats
                self.table.feed_stats(match_day, stats)
                await self.dispatch_events()
        else:
            raise exceptions.InvalidEvents()

    async def resource_result_process(self, data: Dict):
        e_block_id = data.get('eBlockId')
        week = self.get_week_by_block(e_block_id)
        logger.debug('%r Result Block: %d Week : %d', self, e_block_id, week)
        events = data.get('events')
        results = {}
        winning_ids = {}
        result_ids = {}
        week_games = self.league_games.get(week)
        for event in events:
            event_id = event.get('eventId')
            result = event.get('result')
            if not result:
                raise exceptions.NoResultError()
            result_data = result.get('data')
            half_lost = result_data.get('halfLostMarkets')
            half_won = result_data.get('halfWonMarkets')
            refund_stake = result_data.get('refundMarkets')
            handicap_data = {'half_lost': half_lost, 'half_won': half_won, 'refund_stake': refund_stake}
            event_data = week_games.get(event_id)
            team_a = event_data.get('A')
            team_b = event_data.get('B')
            won = result.get('wonMarkets')
            x = set(won)
            y = set(str(_) for _ in range(15, 43))
            r = list(x & y)
            z = r[0]
            score = Markets['Correct_Score'][z]['name'].split('_')
            results[event_id] = {
                'id': event_id, 'A': team_a, 'B': team_b,
                'score': (int(score[1]),
                          int(score[2]))}
            # X is won list (wonMarketIds)
            result_ids[event_id] = [int(_) for _ in won]
            winning_ids[event_id] = handicap_data

        self.table.feed_result(e_block_id, self.league, week, results, result_ids, winning_ids)

        if self.fetching_future:
            not_ready = self.table.check_weeks(self.required_weeks)
            if not_ready:
                # await asyncio.sleep(1)
                await self.get_future_weeks(not_ready)
            else:
                self.fetching_future = False
                logger.debug('%r %r Future result complete. (league=%d)', self, self.user, self.league)
                await self.dispatch_events()
        else:

            if self.phase == self.RESULT_TICKETS:
                weeks = [self.get_week_by_block(week) for week in self.result_blocks]
                missing = self.table.check_weeks(weeks)
                if missing:
                    await self.fetch_result(missing[0], 1)
                else:
                    for live_session_id in self.sessions:
                        live_session = self.user.get_live_session(live_session_id)
                        if live_session.player.status == players.Player.RUNNING:
                            await live_session.player.on_result(self.competition_id)

                    # Attempt to resolve tickets and dispatch events
                    await self.user.validate_competition_tickets(self.competition_id)
                    await self.dispatch_events()
            elif self.phase == self.RESULTS:
                # Always notify players of results
                for live_session_id in self.sessions:
                    live_session = self.user.get_live_session(live_session_id)
                    if live_session.player.status == players.Player.RUNNING:
                        await live_session.player.on_result(self.competition_id)
                await self.dispatch_events()

    # API
    async def dispatch_events(self):
        if self.status == self.SLEEPING:
            return
        try:
            if self.wait_event:
                return
            self.phase = self.DISPATCH
            not_ready = self.table.check_weeks(self.required_weeks)
            if self.future_results and not_ready:
                self.phase = self.FUTURE_RESULT
                await self.get_future_weeks(not_ready)
            else:
                self.phase = self.PLAYING
                self.process_event_time(None)
                e_block_id, week = self.get_next_event()
                if e_block_id > 0:
                    self.e_block_id = e_block_id
                    if self.get_missing_stats(week):
                        self.phase = self.EVENTS_STATS
                        await self.next_block_event()
                        return
                    # await asyncio.sleep(0.5)
                    tasks = {}
                    self.session_events.clear()    # Empty each session event
                    self.result_blocks.clear()      # Empty each result needed to get next week
                    if self.sessions:
                        for live_session_id in self.sessions:
                            live_session = self.user.get_live_session(live_session_id)
                            if live_session.status != LiveSession.SLEEPING:
                                tasks[live_session_id] = asyncio.create_task(live_session.on_events(self.competition_id, week))
                        done: List[asyncio.Task]
                        done, _ = await asyncio.wait(tasks.values(), return_when=asyncio.ALL_COMPLETED)
                        # If not sleeping to await events prediction
                        if not self.wait_event:
                            tickets_pool: List[Ticket] = []
                            for task in done:
                                event: asyncio.Event
                                tickets: List[Ticket]
                                event, tickets = task.result()
                                if not event.is_set():
                                    self.session_events[tickets[0].live_session_id] = event
                                    tickets_pool.extend(tickets)
                            if tickets_pool:
                                for t in tickets_pool:
                                    for e in t.events:
                                        w = e.week
                                        e_block = self.get_block_by_week(w)
                                        self.result_blocks.append(e_block)
                                self.phase = self.TICKETS
                                logger.debug('%r Processing tickets : %d blocks : %s', self, len(tickets_pool),
                                             str(self.result_blocks))
                                await self.process_tickets(tickets_pool)
                                self.result_future = asyncio.create_task(self.get_blocks_result())
                            else:
                                self.phase = self.RESULTS
                                self.result_blocks.append(e_block_id)
                                logger.debug('%r No Tickets available : %d', self, e_block_id)
                                not_ready = self.table.check_weeks(self.required_weeks)
                                if not_ready:
                                    self.phase = self.FUTURE_RESULT
                                    await self.get_future_weeks(not_ready)
                                else:
                                    await self.next_block_result(e_block_id)
                                # await asyncio.sleep(0.5)  # sleep
                else:
                    await self.on_league_completed()
                    self.phase = self.EVENTS
                    await self.next_block_event()
        except Exception:
            print(traceback.print_exc())

    def send(self, resource: str, payload: Dict, method: str = 'Get') -> int:
        if self.socket == 0:
            socket_id, xs = self.user.send(resource, payload, stream_id=self.competition_id, method=method)
        else:
            socket_id, xs = self.user.send(resource, payload, socket_id=self.socket, method=method)
        return xs

    async def receive(self, valid_response: bool, resource: str, payload: Dict):
        try:
            func_name = f'{map_resource_to_name(resource)}_callback'
            callback = getattr(self, func_name)  # type: Callable[[bool, Dict], Coroutine[Any]]
        except AttributeError:
            pass
        else:
            await callback(valid_response, payload)

    async def wss_login_data(self):
        return {
            'gameId': self.competition_id,
            'status': self.status,
            'leagueId': self.league,
            'week': self.week,
        }

    # Jackpot
    def setup_jackpot(self):
        self.jackpot_ready = True
        for live_session_id in self.sessions:
            live_session = self.user.get_live_session(live_session_id)
            live_session.player.setup_jackpot()

    def clear_jackpot(self):
        self.jackpot_ready = False
        for live_session_id in self.sessions:
            live_session = self.user.get_live_session(live_session_id)
            live_session.player.clear_jackpot()

    # Tickets processing
    async def process_tickets(self, tickets: List):
        self.reset_tickets()
        for ticket in tickets:
            content = self.serialize_ticket(ticket)
            setattr(ticket, 'content', content)
            await self.user.register_ticket(ticket)
            live_session = self.user.get_live_session(ticket.live_session_id)
            live_session.ticket_maps.get(self.competition_id)[ticket.ticket_key] = False
            await self.user.ticket_manager.add_ticket(ticket)
            self.active_tickets.append(ticket.ticket_key)

    def serialize_ticket(self, ticket) -> Dict:
        events = ticket.events
        event_datas = []
        for event in events:
            event.playlist_id = self.competition_id
            event_data = {
                'eventId': event.event_id,
                'gameType': {'val': event.game_type},
                'playlistId': event.playlist_id,
                'eventTime': event.event_time,
                'extId': event.ext_id,
                'isBanker': event.is_banker,
                'finalOutcome': event.final_outcome
            }
            bets = []
            for bet in event.bets:
                bet_data = {
                    'marketId': bet.market_id,
                    'oddId': bet.odd_id,
                    'oddName': bet.odd_name,
                    'oddValue': bet.odd_value,
                    'status': bet.status,
                    'profitType': bet.profit_type,
                    'stake': bet.stake
                }
                bets.append(bet_data)
            event_data['bets'] = bets
            data = {
                'classType': 'FootballTicketEventData',
                'participants': event.participants,
                'leagueId': event.league,
                'matchDay': event.week,
                'eventNdx': event.event_ndx
            }
            event_data['data'] = data
            event_datas.append(event_data)
        ticket_data = {
            'events': event_datas,
            'systemBets': ticket.system_bets,
            'ticketType': ticket.mode
        }
        return ticket_data

    def get_ticket_validation_data(self) -> Tuple[Dict, Dict]:
        return self.table.results_ids_pool, self.table.winning_ids_pool

    async def on_ticket_resolve(self, ticket: Ticket):
        live_session = self.user.get_live_session(ticket.live_session_id)
        await live_session.player.on_ticket(ticket)

    def reset_tickets(self):
        self.active_tickets.clear()

    # Get Weeks info
    def get_next_event(self) -> Tuple[int, int]:
        a = set(range(1, self.max_week + 1))
        b = set(self.table.event_block_map)
        c = a - b
        if c:
            week = min(c)
            e_block_id = self.get_block_by_week(week)
            if isinstance(e_block_id, int) and isinstance(week, int):
                return e_block_id, week
        return -1, -1

    def get_missing_blocks(self) -> List:
        all_weeks = set(i for i in range(1, self.max_week + 1))
        block_weeks = set(self.blocks.values())
        return list(all_weeks - block_weeks)

    def get_missing_stats(self, week: int):
        if self.table.get_week_stats(week):
            return False
        return True

    def get_block_by_week(self, week: int) -> Optional[int]:
        a = {v: k for k, v, in self.blocks.items()}
        return a.get(week)

    def get_week_by_block(self, e_block_id: int) -> Optional[int]:
        return self.blocks.get(e_block_id)

    def get_required_weeks(self):
        used_weeks = []
        for live_session_id in self.sessions:
            live_session = self.user.get_live_session(live_session_id)
            live_session.player.get_required_weeks(self.competition_id)
            used_weeks.extend(live_session.player.required_weeks(self.competition_id))
        all_weeks = set(i for i in range(1, self.max_week + 1))
        return list(all_weeks - set(used_weeks))

    def extend_required_weeks(self, weeks: List[int]):
        self.required_weeks.extend(set(weeks))

    def reset_league(self, league: int):
        self.league_games.clear()
        self.blocks.clear()
        self.cached = False
        self.required_weeks.clear()
        self.league = league
        self.table.clear_table()
        self.table.setup_league(league)

    def reset_blocks(self, match_day: int):
        a = int(match_day / 10)
        b = (match_day % 10)
        if not a and b <= 1:
            b = 0
        if b:
            a += 1
        self.max_previous_block = a
        self.previous_block_count = 0

        r = self.max_week - match_day
        s = int(r / 10)
        s += 1
        self.max_future_block = s
        self.future_block_count = 0

    async def get_future_weeks(self, weeks: List[int]):
        self.fetching_future = True
        week = weeks[0]
        e_block = self.get_block_by_week(week)
        await self.fetch_result(e_block, 1)

    # Event time
    def get_event_time(self):
        now = datetime.now(tz=timezone.utc)
        midnight = now.replace(hour=0, minute=0, second=0)
        time_span = int((now - midnight).total_seconds())
        return int(now.timestamp() + self.offset)

    def process_event_time(self, event_time):
        if event_time is None:
            now = time.time()
            if self.event_time_enabled:
                self.event_time = now + self.event_time_interval
            else:
                self.event_time = now
        else:
            self.event_time = event_time

    async def await_event_time(self):
        now = int(time.time())
        t = self.event_time - now
        if t > 0:
            await asyncio.sleep(t)

    # Save League
    async def on_league_completed(self):
        if self.table.is_complete():
            league_info = {}
            for week, week_data in self.league_games.items():
                week_results = self.table.get_week_results(week)
                week_stats = self.table.get_week_stats(week)
                week_result_ids = self.table.results_ids_pool.get(week)
                week_info = {}
                for event_id, event_data in week_data.items():
                    team_a = event_data.get('A')
                    team_b = event_data.get('B')
                    odds = event_data.get('odds')
                    r_ids = week_result_ids.get(event_id)
                    half_score = list(set(r_ids) & {152, 153, 154})
                    event_result = week_results.get(event_id)
                    event_stats = week_stats.get(event_id)
                    score = list(event_result.get('score'))
                    week_info[event_id] = {'t_a': team_a, 't_b': team_b, 'stats': event_stats, 'odds': odds[:3],
                                           'score': score, 'h_score': half_score[0]}
                league_info[week] = week_info
            await self.store_competition(self.competition_id, self.league, league_info)

    async def store_competition(self, game_id: int, league: int, data: Dict):
        await dump_data(settings.DUMP_DIR + "/" + self.user.provider.provider_name, self.user.username, self.competition_id,
                        league, data)
        logger.debug('%r {%d} upload league=%d', self, game_id, league)

    # Shutdown
    async def exit(self):
        pass
        #futures = {}
        #for player_id, player in self.players.items():
        #    player.closing = True
        #    futures[player_id] = asyncio.create_task(player.exit())
        #if futures:
        #    done, p = await asyncio.wait(list(futures.values()), return_when=asyncio.ALL_COMPLETED)
        #socket = self.user.get_socket(self.competition_id)

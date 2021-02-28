from __future__ import annotations

import asyncio
import enum
import time
from operator import attrgetter
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING, Tuple

from vbet.core.orm import save_ticket, update_ticket
from vbet.utils.log import async_exception_logger, get_logger
from vbet.utils.parser import Resource

if TYPE_CHECKING:
    from vbet.game.user import User
    from vweb.vclient.models import Tickets, LiveSession
    from vbet.core.socket_manager import Socket
    from vbet.core.provider import Provider

logger = get_logger('tickets')


class TicketStatus(enum.IntEnum):
    READY = 0
    WAITING = 1
    SENT = 2
    FAILED = 3
    SUCCESS = 4
    VOID = -1
    ERROR_CREDIT = 5
    NETWORK = 6
    DISCARD = 7


class Bet:
    def __init__(
            self, odd_id: int, market_id: str, odd_value: float, odd_name: str,
            stake: float):
        self.odd_id: int = odd_id
        self.market_id: str = market_id
        self.odd_value: float = odd_value
        self.odd_name: str = odd_name
        self.stake: Optional[float] = stake
        self.profit_type: str = "NONE"
        self.status: str = 'OPEN'

    def __str__(self):
        return "OddId: {} MarketId: {} OddName: {} OddValue: {} Stake {}".format(self.odd_id,
                                                                                 self.market_id, self.odd_name,
                                                                                 self.odd_value, self.stake)


class Event:
    def __init__(self, event_id: int, league: int, week: int,
                 participants: List[Dict]):
        self.event_id: int = event_id
        self.bets: List[Bet] = []
        self.final_outcome: List[int] = []
        self.game_type: str = "GL"
        self.playlist_id: Optional[int] = None
        self.event_time: Optional[float] = None
        self.ext_id: Optional[Any] = None
        self.is_banker: bool = False
        # data
        self.league: int = league
        self.week: int = week
        self.event_ndx: Optional[int] = None
        self.participants: List[Dict] = participants

    @property
    def stake(self):
        _stake = 0
        for bet in self.bets:
            _stake += bet.stake
        return _stake

    def get_formatted_participants(self) -> Tuple:
        home = self.participants[0].get('fifaCode')
        away = self.participants[1].get('fifaCode')
        return home, away

    @property
    def min_win(self):
        m = 0
        for bet in self.bets:
            odd = bet.odd_value
            stake = bet.stake
            m = round(odd * stake, 2)
        return m

    def __str__(self):
        bets = [bet.__str__() for bet in self.bets]
        bets_str = "\n".join(bets)
        return f'Event Id : {self.event_id} {self.get_formatted_participants()} \n{bets_str}'

    def add_bet(self, bet: Bet):
        self.bets.append(bet)


class Ticket:
    SINGLE = 'SINGLE'
    MULTIPLE = 'MULTIPLE'

    def __init__(self, game_id: int, player: str):
        self.game_id: int = game_id
        self.demo = True
        self.db_ticket: Optional[Tickets] = None
        self.db_live_session: Optional[LiveSession] = None
        self.ticket_key: Optional[int] = None
        self.player: str = player
        self.content: Optional[Dict] = None
        self.events: List[Event] = []
        self.priority: int = 0
        self.status: TicketStatus = TicketStatus.READY
        self.sent: bool = False
        self.resolved: bool = False
        self.socket_id: Optional[int] = None
        self.sent_time: float = 0
        self.live_session_id: int = 0
        self.xs: int = -1
        self._mode: str = ''
        self._min_winning: float = 0
        self._max_winning: float = 0
        self._min_bonus: float = 0
        self._max_bonus: float = 0
        self._total_won: float = 0
        self._grouping: int = 0
        self._system_count: int = 0
        self._winning_count: int = 0
        self._winning_data: Dict = {}
        self._system_bets: List[Dict] = []
        self._stake: float = 0
        self.ip: str = ''
        self.server_hash: str = ''
        self.ticket_id: int = 0
        self.time_send: str = ''
        self.time_resolved: str = ''
        self.time_paid: str = ''
        self.time_register: str = ''
        self.ticket_status: str = 'OPEN'

    def __str__(self):
        events = [event.__str__() for event in self.events]
        events_str = "\n".join(events)
        return f'Ticket : {self.mode} State : {self.status} Stake : {self.stake} \n{events_str}'

    @property
    def mode(self):
        if len(self.events) == 1:
            self._mode = Ticket.SINGLE
        else:
            self._mode = Ticket.MULTIPLE
        return self._mode

    @property
    def stake(self):
        return self._stake

    @property
    def total_won(self):
        return self._total_won

    @property
    def grouping(self):
        return self._grouping

    @property
    def system_count(self):
        return self._system_count

    @property
    def winning_count(self):
        return self._winning_count

    @property
    def min_winning(self):
        return self._min_winning

    @property
    def max_winning(self):
        return self._max_winning

    @property
    def min_bonus(self):
        return self._min_bonus

    @property
    def max_bonus(self):
        return self._max_bonus

    @property
    def winning_data(self):
        self._winning_data = {
            'limitMaxPayout': 200000,
            'minWinning': self.min_winning,
            'maxWinning': self.min_winning,
            'minBonus': self.min_bonus,
            'maxBonus': self.max_bonus,
            'winningCount': self.winning_count
        }
        return self._winning_data

    @property
    def system_bets(self):
        self._system_bets = [{
            'grouping': self.grouping,
            'systemCount': self.system_count,
            'stake': self.stake,
            'winningData': self.winning_data
        }]
        return self._system_bets

    def add_event(self, event: Event):
        self.events.append(event)

    def resolve(self, results: Dict) -> float:
        self._total_won = 0
        if self.mode == Ticket.SINGLE:
            for event in self.events:
                event_data = results.get(event.event_id)
                won_data = event_data[0]
                winnings = event_data[1]
                refund_stake = winnings.get('refund_stake')
                half_lost = winnings.get('half_lost')
                half_won = winnings.get('half_won')
                for bet in event.bets:
                    if str(bet.odd_id) in refund_stake:
                        self._total_won += bet.stake
                    elif str(bet.odd_id) in half_lost:
                        self._total_won += (bet.stake / 2)
                    elif str(bet.odd_id) in half_won:
                        self._total_won += round((bet.stake / 2) * bet.odd_value, 2)
                    elif bet.odd_id in won_data:
                        won = round(bet.stake * bet.odd_value, 2)
                        self._total_won += won
                break
        else:
            if self.winning_count >= 1 and self.grouping == 1:
                for event in self.events:
                    for bet in event.bets:
                        if bet.odd_id in results[event.event_id]:
                            self._total_won += round(bet.stake * bet.odd_value, 2)
            if self.winning_count == 1 and self.grouping > 1:
                total_odd = 1
                for event in self.events:
                    for bet in event.bets:
                        if bet.odd_id in results[event.event_id]:
                            total_odd *= bet.odd_value
                        else:
                            return self._total_won
                self._total_won = total_odd * self.stake
        return self._total_won

    def can_resolve(self, results: Dict, winning_ids: Dict) -> Dict:
        required_results = {}
        for event in self.events:
            week_result = results.get(event.week, {})
            week_winnings = winning_ids.get(event.week, {})
            if not week_result:
                return {}
            event_data = week_result.get(event.event_id, [])
            event_winnings = week_winnings.get(event.event_id, {})
            if not event_data:
                return {}
            required_results[event.event_id] = [event_data, event_winnings]
        return required_results

    def set_priority(self, priority: int):
        self.priority = priority

    def is_valid(self) -> bool:
        return self.events != {}

    def sent_notify(self, xs, socket_id):
        self.xs = xs
        self.socket_id = socket_id
        self.sent = True
        self.status = TicketStatus.SENT
        self.sent_time = time.time()

    def on_place(self):
        self.db_ticket.status = self.status
        self.db_ticket.ticket_id = self.ticket_id
        self.db_ticket.ticket_status = self.ticket_status
        self.db_ticket.time_paid = self.time_paid
        self.db_ticket.time_send = self.time_send
        self.db_ticket.time_register = self.time_register
        self.db_ticket.time_resolved = self.time_resolved
        self.db_ticket.server_hash = self.server_hash
        self.db_ticket.ip = self.ip

    def on_pay(self):
        self.db_ticket.time_paid = self.time_paid
        self.db_ticket.time_resolved = self.time_resolved
        self.db_ticket.resolved = self.resolved

    def on_lost(self):
        self.db_ticket.resolved = self.resolved
        self.ticket_status = 'LOST'

    def on_void(self):
        self.db_ticket.ticket_status = 'VOID'

    async def save(self):
        self.db_ticket.ticket_status = self.ticket_status
        self.db_ticket.status = self.status
        await update_ticket(self.db_ticket)


class TicketManager:
    DEFAULT_TICKET_INTERVAL = 0
    JACKPOT_BEFORE = 0
    JACKPOT_AFTER = 1
    JACKPOT_NIL = 2

    ticket_queue: asyncio.Queue
    active_tickets: Dict[int, Dict[int, Ticket]]
    last_ticket_time: float
    buffer_tickets: bool
    socket_event: asyncio.Event
    send_lock: asyncio.Lock
    reg_lock: asyncio.Lock
    pool_lock: asyncio.Lock
    ticket_sender_task: asyncio.Task
    _ticket_wait: asyncio.Event
    sockets: List[int]
    socket_map: Dict[int, Dict[int, int]]
    min_sockets: int
    jackpot_resume: int
    t_lock: asyncio.Lock
    provider: Provider

    def __init__(self, provider: Provider):
        self.provider = provider
        self.ticket_queue = asyncio.Queue()
        self.active_tickets = {}
        self.last_ticket_time = time.time() - self.DEFAULT_TICKET_INTERVAL
        self.buffer_tickets = True  # Await response of last ticket before sending next
        self.send_lock = asyncio.Lock()
        self.reg_lock = asyncio.Lock()
        self.pool_lock = asyncio.Lock()
        self.ticket_sender_task = asyncio.create_task(self.ticket_listener())
        self._ticket_wait = asyncio.Event()
        self.socket_event = asyncio.Event()
        self.sockets = []
        self.streams = []
        self.socket_map = {}
        self.min_sockets = 1
        self.active_game_id = 0
        self.active_ticket_key = 0
        self.jackpot_resume = self.JACKPOT_NIL
        self.t_lock = asyncio.Lock()

    @async_exception_logger('listener')
    async def ticket_listener(self):
        logger.debug('%r Queue listener started', self.user)
        while True:
            await self.wait_ticket_interval()
            ticket_data = await self.ticket_queue.get()
            game_id, ticket_key = ticket_data[0], ticket_data[1]
            self.active_game_id, self.active_ticket_key = game_id, ticket_key
            ticket = await self.find_ticket(game_id, ticket_key)
            if ticket is not None:
                await self.inner_sender(ticket)
            else:
                break
        logger.debug('%r Queue listener stopped', self.user)

    async def inner_sender(self, ticket: Ticket):
        if self.user.account_manager.is_bonus_ready():
            if not self.user.jackpot_ready:
                self.user.jackpot_setup()
        else:
            if self.user.jackpot_ready:
                self.user.jackpot_reset()
        await self.send_ticket(ticket)

    async def register_ticket(self, ticket: Ticket) -> int:
        async with self.t_lock:
            ticket_key = await save_ticket(self.user.provider, self.user.db_user, self.user.db_provider, ticket)
            ticket.ticket_key = ticket_key
            return ticket_key

    async def send_ticket(self, ticket: Ticket):
        async with self.send_lock:
            if ticket.demo:
                await self.resolve_demo_ticket(ticket)
            else:
                credit = await self.user.account_manager.credit
                # FIXME: ticket.stake
                if credit >= ticket.stake:
                    logger.debug('[%d] %r [%s:%d:%d] Stake : %f', ticket.game_id,
                                 self.user, ticket.player, ticket.live_session_id, ticket.ticket_key, ticket.stake)
                    await self.resolve_ticket(ticket)
                else:
                    ticket.status = TicketStatus.ERROR_CREDIT
                    logger.warning('[%d] %r [%s:%d:%d] Error credit : %f', ticket.game_id, self.user, ticket.player,
                                   ticket.live_session_id, ticket.ticket_key, ticket.stake)
                    self.last_ticket_time = time.time() - self.DEFAULT_TICKET_INTERVAL
                    # No ticket sent so can send instant

    async def resolve_ticket(self, ticket: Ticket):
        ticket_data = self.user.resource_tickets(ticket.content)
        socket = await self.get_available_socket()
        while True:
            if not socket:
                socket = await self.get_available_socket()
            else:
                break
        socket_id, xs = self.user.send(Resource.TICKETS, body=ticket_data, method='POST', socket_id=socket.socket_id)
        ticket.status = TicketStatus.SENT
        ticket.sent_notify(xs, socket.socket_id)
        socket_map = self.socket_map.get(socket.socket_id, {})
        socket_map[ticket.xs] = ticket.game_id
        self.socket_map[socket.socket_id] = socket_map
        if not self.user.jackpot_ready:
            self.user.send(Resource.SYNC, body={}, socket_id=socket.socket_id)

    async def resolve_demo_ticket(self, ticket: Ticket):
        live_session = self.user.get_live_session(ticket.live_session_id)
        await live_session.account.account.borrow(ticket.stake)
        ticket.status = TicketStatus.SUCCESS
        logger.debug('[%d] %r [%s:%d:%d] Demo ticket success %f', ticket.game_id,
                     self.user, ticket.player, ticket.live_session_id, ticket.ticket_key, ticket.stake)
        self.user.account_manager.total_stake = ticket.stake
        live_session = self.user.get_live_session(ticket.live_session_id)
        live_session.ticket_maps.get(ticket.game_id)[ticket.ticket_key] = True
        ticket.ticket_status = 'OPEN'
        ticket.status = TicketStatus.SUCCESS
        ticket.on_place()
        await ticket.save()
        self.user.tickets_complete(ticket.game_id, ticket.live_session_id)

    async def ticket_success(self, ticket: Ticket):
        ticket.status = TicketStatus.SUCCESS
        live_session = self.user.get_live_session(ticket.live_session_id)
        live_session.ticket_maps.get(ticket.game_id)[ticket.ticket_key] = True
        self.user.tickets_complete(ticket.game_id, ticket.live_session_id)

    async def ticket_failed(self, error_code: int, ticket: Ticket):
        # Assign error code
        if error_code == 602:
            ticket.status = TicketStatus.VOID
        elif error_code == 603:
            ticket.status = TicketStatus.VOID
        elif error_code == 605:
            ticket.status = TicketStatus.ERROR_CREDIT
        else:
            ticket.status = TicketStatus.FAILED

        # Retry sending
        if error_code in [604, 500]:
            ticket.status = TicketStatus.READY

        if ticket.status == TicketStatus.READY:
            await self.ticket_queue.put((ticket.game_id, ticket.ticket_key))

        # Invalid block to place ticket
        if error_code == 602:
            live_session = self.user.get_live_session(ticket.live_session_id)
            live_session.ticket_maps.get(ticket.game_id)[ticket.ticket_key] = True
            self.user.tickets_complete(ticket.game_id, ticket.live_session_id)

    async def add_ticket(self, ticket: Ticket):
        async with self.pool_lock:
            competition_tickets = self.active_tickets.setdefault(ticket.game_id, {})
            competition_tickets[ticket.ticket_key] = ticket
            if ticket.status == TicketStatus.READY:
                await self.ticket_queue.put((ticket.game_id, ticket.ticket_key))
                ticket.status = TicketStatus.WAITING

    async def remove_ticket(self, ticket: Ticket):
        async with self.pool_lock:
            competition_tickets = self.active_tickets.get(ticket.game_id, {})
            if competition_tickets:
                competition_tickets.pop(ticket.ticket_key)

    async def find_ticket(self, game_id: int, ticket_key: int) -> Optional[Ticket]:
        competition_tickets = self.active_tickets.get(game_id, {})
        if competition_tickets:
            ticket = competition_tickets.get(ticket_key, None)
            return ticket

    async def find_ticket_by_xs(self, socket_id, xs: int) -> Optional[Ticket]:
        async with self.send_lock:
            socket_map = self.socket_map.get(socket_id, {})
            try:
                game_id = socket_map.pop(xs)
                if socket_map:
                    self.socket_map[socket_id] = socket_map
                else:
                    self.socket_map.pop(socket_id)
            except KeyError:
                pass
            else:
                if not self._ticket_wait.is_set():
                    self._ticket_wait.set()
                competition_tickets = self.active_tickets.get(game_id, {})
                for ticket_key, ticket in competition_tickets.items():
                    if ticket.xs == xs and ticket.socket_id == socket_id:
                        return ticket

    def find_ticket_by_id(self, ticket_id: int) -> Optional[Ticket]:
        for competition_tickets in self.active_tickets.values():
            for ticket in competition_tickets.values():
                if ticket.ticket_id == ticket_id:
                    return ticket

    async def check_pending_tickets(self, game_id: int):
        competition_tickets = self.active_tickets.get(game_id)
        for ticket_key, ticket in competition_tickets.items():
            if ticket.status != TicketStatus.SUCCESS and ticket.status != TicketStatus.VOID and \
                    ticket.status != TicketStatus.WAITING:
                return True
        return False

    async def resume_competition_tickets(self, game_id: int) -> bool:
        competition_tickets = self.active_tickets.get(game_id)
        a = False
        for ticket_key, ticket in competition_tickets.items():
            if ticket.status == TicketStatus.READY or ticket.status == TicketStatus.WAITING or \
                    ticket.status == TicketStatus.FAILED:
                a = True
        return a

    async def reset_competition_tickets(self, game_id: int):
        competition_tickets = self.active_tickets.get(game_id, {})
        for ticket_key, ticket in competition_tickets.items():
            ticket.status = TicketStatus.VOID
        self.active_tickets[game_id] = {}

    async def validate_competition_tickets(self, game_id: int):
        competition_tickets = self.active_tickets.get(game_id, {})
        if competition_tickets:
            results, winning_ids = self.user.get_competition_results(game_id)
            for ticket in competition_tickets.values():
                if ticket.status == TicketStatus.SUCCESS and not ticket.resolved:
                    validation_data = ticket.can_resolve(results, winning_ids)
                    if validation_data:
                        ticket.resolve(validation_data)
                        ticket.resolved = True
                        ticket.db_ticket.resolved = ticket.resolved
                        await self.user.resolved_competition_ticket(ticket)
                        if ticket.demo:
                            credit = await self.user.account_manager.demo_credit
                        else:
                            credit = await self.user.account_manager.credit
                        bonus_level = self.user.account_manager.bonus_level
                        jackpot_val = self.user.account_manager.jackpot_value
                        jackpot_amount = self.user.account_manager.jackpot_amount
                        total_stake = self.user.account_manager.total_stake
                        credit_str = f'{credit:.2f}'
                        # credit_str = credit_str.ljust(9)
                        jackpot_val_str = f'{jackpot_val:.2f}%'
                        # jackpot_val_str = jackpot_val_str.ljust(6)
                        jackpot_amount_str = f'{jackpot_amount:.2f}'
                        # jackpot_amount_str = jackpot_amount_str.ljust(7)
                        bonus_level_str = f'L{bonus_level + 1}'
                        account_str = f'(bal={credit_str}, level={bonus_level_str}, val={jackpot_val_str})'
                        stake_str = f'{ticket.stake:.2f}'
                        # stake_str = stake_str.ljust(9)
                        won_str = f'{ticket.total_won:.2f}'
                        # won_str = won_str.ljust(9)
                        total_stake_str = f'{total_stake:.2f}'
                        # total_stake_str = total_stake_str.ljust(9)
                        bet_str = f'(stake={stake_str}, won={won_str}, total={total_stake_str})'
                        logger.info('[%d] %r [%s:%d:%d] %s  %s', game_id, self.user, ticket.player,
                                    ticket.live_session_id, ticket.ticket_key,  account_str, bet_str)
                        body = {ticket.db_ticket.ticket_key: {
                            'data': {
                                'player': ticket.db_ticket.live_session.data,
                                'status': ticket.db_ticket.status,
                                'ticket_id': ticket.db_ticket.ticket_id,
                                'ticket_key': ticket.db_ticket.ticket_key,
                                'ticket_status': ticket.db_ticket.ticket_status,
                                'won_data': ticket.db_ticket.won_data,
                                'time_created': ticket.db_ticket.time_created.isoformat()
                            },
                            'ticket': ticket.db_ticket.details}}
                        for session_key in self.user.ws_sessions.keys():
                            self.user.provider.send_to_session(self.user.username, session_key, "ticket_resolve", body)
                            body2 = {}
                            live_session = self.user.get_live_session(ticket.live_session_id)
                            body2[ticket.live_session_id] = {
                                'sessionId': live_session.session_id,
                                'accountId': live_session.account.account_id,
                                'demo': live_session.account.demo,
                                'player': live_session.player.name,
                                'competitions': live_session.competitions,
                                'target_amount': live_session.target_amount,
                                'stake': live_session.stake,
                                'won': live_session.won
                            }
                            self.user.provider.send_to_session(self.user.username, session_key, "sessions_update", body2)
                        await self.user.sync_sessions()

    async def wait_ticket_interval(self):
        if self.user.jackpot_ready:
            self.last_ticket_time = time.time()
            return
        now = time.time()
        gap = now - self.last_ticket_time
        if self.DEFAULT_TICKET_INTERVAL > 0:
            to_sleep = self.DEFAULT_TICKET_INTERVAL - gap
            if to_sleep > 0:
                await asyncio.sleep(to_sleep)
        self.last_ticket_time = time.time()

    async def get_available_socket(self) -> Socket:
        sockets = []
        for socket_id in self.sockets:
            socket = self.user.get_socket(socket_id)
            if socket.status == socket.CONNECTED:
                sockets.append(socket)
        while not sockets:
            self._ticket_wait.clear()
            await self._ticket_wait.wait()
            sockets = []
            for socket_id in self.sockets:
                socket = self.user.get_socket(socket_id)
                if socket.status == socket.CONNECTED:
                    sockets.append(socket)
        if sockets:
            socket = sorted(sockets, key=attrgetter('last_used'))[0]
            socket.last_used = time.time()
            return socket

    async def stream_online(self, stream_id: int):
        if not self._ticket_wait.is_set():
            self._ticket_wait.set()

    async def stream_lost(self, stream_id: int):
        for socket_id in self.sockets:
            socket = self.user.get_socket(socket_id)
            if socket.status == socket.CONNECTED:
                return
        self._ticket_wait.clear()

    async def stream_offline(self, socket_id: int):
        try:
            i = self.sockets.index(socket_id)
            self.sockets.remove(socket_id)
            self.streams.pop(i)
        except ValueError:
            pass
        finally:
            if not self.sockets:
                self.user.close_event.set()

    async def setup_sockets(self):
        for i in range(0, self.min_sockets):
            s_id = 400 + i
            socket = await self.user.create_stream(s_id, reuse=False)
            self.streams.append(s_id)
            self.sockets.append(socket.socket_id)

    def close_sockets(self):
        for socket_id in self.sockets:
            socket = self.user.get_socket(socket_id)
            if socket:
                asyncio.create_task(socket.wait_closed())

    def exit(self):
        self.close_sockets()
        self.ticket_sender_task.cancel()

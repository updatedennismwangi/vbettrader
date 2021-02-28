from __future__ import annotations

import asyncio
import traceback
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Tuple, Union

from vbet.core.mixin import StatusMap
from vbet.core.ws_session import WsSession
from vbet.utils.log import get_logger
from vbet.core.orm import create_live_session, load_tickets, load_active_tickets
from vbet.utils.parser import Resource, get_ticket_timestamp
from .accounts.manager import AccountManager
from .competition import LeagueCompetition
from .provider_settings import ProviderSettings
from .session import LiveSession
from .tickets import Ticket, TicketManager, TicketStatus
import time
if TYPE_CHECKING:
    from vbet.core.provider import Provider
    from vbet.core.socket_manager import Socket
    from vweb.vclient.models import User as UserAdmin, Providers, LiveSession as DbLiveSession

logger = get_logger('user')


class User(StatusMap):
    provider: Provider
    db_provider: Providers
    db_user: UserAdmin
    db_live_session: DbLiveSession
    status: str
    active_event: asyncio.Event
    close_event: asyncio.Event
    sockets: List[int]
    live_sessions: Dict[int, LiveSession]
    competitions: Dict[int, LeagueCompetition]
    settings: ProviderSettings
    account_manager: AccountManager
    ticket_manager: TicketManager
    jackpot_ready: bool
    ws_sessions: Dict[str, WsSession]
    msg_map: Dict[str, int]

    def __init__(self, provider_instance: Provider, provider: Providers):
        self.provider = provider_instance
        self.db_provider = provider
        self.db_user = provider.user
        self.status = self.OFFLINE
        self.active_event = asyncio.Event()
        self.close_event = asyncio.Event()
        self.channel_future = None
        self.sockets = []
        self.live_sessions = {}
        self.competitions = {}
        self.settings = ProviderSettings()
        self.account_manager = AccountManager(self)
        self.ticket_manager = TicketManager(self)
        self.jackpot_ready = False
        self.ws_sessions = {}
        self.msg_map = {}
        self.ticket_check = {}

    @property
    def username(self) -> str:
        return self.db_provider.username

    @property
    def user_id(self) -> int:
        return int(self.db_provider.token.get('id'))

    @property
    def cookies(self) -> Dict:
        return self.db_provider.token.get('cookies')

    @property
    def token(self) -> str:
        return self.db_provider.token.get('token')

    def __repr__(self):
        return '%r [%s]' % (self.provider, self.username)

    def online(self):
        if self.status == self.OFFLINE:
            self.status = self.ACTIVE
            if not self.active_event.is_set():
                self.active_event.set()

            # Setup default com websocket
            asyncio.ensure_future(self.setup_sockets())

            # Restore previous active sessions
            # asyncio.ensure_future(self.restore_live_sessions())
            # Setup ticket manager sockets which are different from competition sockets
            asyncio.ensure_future(self.ticket_manager.setup_sockets())

    async def setup_sockets(self):
        if 0 not in self.sockets:
            socket = await asyncio.ensure_future(self.create_stream(0, False))
            self.sockets.append(socket.socket_id)

    def offline(self):
        self.status = self.OFFLINE
        if self.active_event.is_set():
            self.active_event.clear()

        for live_session in self.live_sessions.values():
            live_session.stop()

        for socket in self.sockets:
            pass
            #socket.socket_id

    # Resources
    def resource_tickets(self, details: Dict):
        return {
            'tagsId': self.settings.tags_id,
            'timeSend': get_ticket_timestamp(),
            'oddSettingsId': self.settings.odd_settings_id,
            'taxesSettingsId': self.settings.taxes_settings_id,
            'currency': self.settings.currency,
            'sellStaff': self.settings.auth_staff,
            'gameType': {
                'val': "ME"
            },
            'details': details,
        }

    @staticmethod
    def resource_playlists(competition_ids: List[int]):
        return {
            'ids': ",".join([str(_) for _ in competition_ids])  # TODO: Monkeypatch
        }

    @staticmethod
    def resource_ticket_by_id(n, ticket_id: int = None) -> Dict:
        data = {
            'n': n,
            'filter': None,
        }
        if ticket_id:
            data.setdefault('ticketId', ticket_id)
        return data

    # Accounts
    async def setup_session(self, body: Dict):
        # Setup balance
        session_status = body.get('sessionStatus')  # type: Dict
        await self.process_session_status(session_status)
        # Game settings
        if not self.settings.configured:
            self.settings.configured = True
            self.settings.process_displays(body.get('displays'))
            self.settings.process_game_settings(body.get('gameSettings'))
            self.settings.process_localization(body.get('localization'))
            self.settings.process_taxes_settings(body.get('taxesSettings'))
            self.settings.auth = body.get('auth')
            self.settings.ext_data = body.get('extData')
            self.settings.odd_settings_id = body.get('oddSettingsId')
            self.settings.tags_id = body.get('tagsId')

    async def process_session_status(self, session_status: Dict):
        credit = session_status.get('credit')  # type: float
        jackpot = session_status.get('jackpots')  # type: List
        if jackpot:
            user_jackpot = jackpot[0]  # type: Dict
            self.account_manager.bonus_level = user_jackpot.get('bonusLevel')
            self.account_manager.jackpot_amount = user_jackpot.get('amount')

        # Enable jackpot
        if self.account_manager.is_bonus_ready():
            if not self.jackpot_ready:
                self.jackpot_setup()
        else:
            if self.jackpot_ready:
                self.jackpot_reset()
        # update credit
        if credit > 0:
            await self.account_manager.update(credit)

    def jackpot_setup(self):
        # Notify competitions of jackpot ready
        for a in self.competitions.values():
            a.setup_jackpot()

        self.jackpot_ready = True
        self.ticket_manager.buffer_tickets = False
        if self.ticket_manager.jackpot_resume == TicketManager.JACKPOT_NIL:
            self.ticket_manager.jackpot_resume = TicketManager.JACKPOT_AFTER
        else:
            self.ticket_manager.jackpot_resume = TicketManager.JACKPOT_BEFORE

        if self.ticket_manager.jackpot_resume == TicketManager.JACKPOT_AFTER:
            pass
            # self.ticket_manager.buffer_tickets = True
        logger.info('%r Jackpot ready %f', self, self.account_manager.jackpot_amount)

    def jackpot_reset(self):
        # Notify competitions of jackpot ready
        for a in self.competitions.values():
            a.clear_jackpot()

        self.jackpot_ready = False
        self.ticket_manager.buffer_tickets = False
        self.ticket_manager.jackpot_resume = TicketManager.JACKPOT_NIL

    # Callbacks
    async def login_callback(self, socket_id: int, valid_response: bool, body: Dict):
        socket = self.provider.sock_manager.sockets.get(socket_id)
        stream = socket.get_user_stream(self.user_id)
        if valid_response and isinstance(body, dict):
            client_id = body.get('clientId', None)  # type: Optional[str]
            if isinstance(client_id, str):
                client_id = body.pop('clientId')  # type: str
                stream.client_id = client_id
                stream.status = stream.AUTHORIZED
                await self.setup_session(body)
                logger.info('%r Authentication success %r', self, stream)
                await self.stream_online(stream.stream_id)
                return
        # TODO: Respawn failed stream only
        logger.error('%r Authentication failed %r %s', self, stream, str(body))
        stream.status = stream.UNAUTHENTICATED

    async def playlists_callback(self, valid_response: bool, body: List[Dict]):
        try:
            if valid_response:
                for competition_data in body:
                    competition_id = competition_data.get('id')
                    logger.debug('%r installing competition %d', self, competition_id)
                    self.create_competition(competition_id, competition_data.get('mode'),
                                            competition_data.get('participantTemplates'))
        except AttributeError:
            logger.error('error %s ', str(body))
            raise

    async def sync_callback(self, valid_response: bool, body: Dict):
        if valid_response:
            session_status = body.get('sessionStatus', {})  # type: Dict
            if session_status:
                await self.process_session_status(session_status)

    async def ticket_callback(self, game_id: int, xs: int, valid_response: bool, body: Dict):
        ticket: Union[Ticket, None]
        ticket = await self.ticket_manager.find_ticket_by_xs(game_id, xs)
        if not ticket:
            print(f'{game_id}, {xs}, {valid_response}, {self.ticket_manager.socket_map}')
        else:
            # logger.debug('%r (comp_id=%d, player=%s) ticket response \n%s',
            #              self, ticket.game_id, ticket.player, ticket)
            transaction = body.get('transaction', None)  # type: Dict
            if transaction:
                response_ticket = body.get('ticket')  # type: Dict
                ticket.ticket_id = response_ticket.get('ticketId')
                ticket.time_send = response_ticket.get('timeSend')
                ticket.time_register = response_ticket.get('timeRegister')
                ticket.ip = response_ticket.get('ip')
                ticket.server_hash = response_ticket.get('serverHash')
                ticket.ticket_status = response_ticket.get('status')
                new_credit = transaction.get('newCredit')  # type: float
                self.account_manager.total_stake = ticket.stake
                await self.account_manager.update(new_credit)
                logger.debug('[%d] %r [%s:%d:%d] Ticket Success %d', ticket.game_id,
                             self, ticket.player, ticket.live_session_id, ticket.ticket_key, ticket.ticket_id)
                await self.ticket_manager.ticket_success(ticket)

                ticket.on_place()
                await ticket.save()
            else:
                error_code = int(body.get('errorCode', None))
                message = body.get('message', None)
                logger.warning('[%d] %r [%s:%d:%d] Code: %d Message: %s', ticket.game_id,
                               self, ticket.player, ticket.live_session_id, ticket.ticket_key, error_code, str(message))
                await self.ticket_manager.ticket_failed(error_code, ticket)

    async def tickets_find_by_id_callback(self, xs, valid_response: bool, body: Any):
        # TODO: Type checks
        if valid_response and isinstance(body, list):
            if body:
                ticket: Dict
                if xs in self.ticket_check:
                    game_id, ticket_key = self.ticket_check.pop(xs)
                    print(game_id, ticket_key)
                    t = await self.ticket_manager.find_ticket(game_id, ticket_key)
                    for ticket in body:
                        ticket_id = ticket.get('ticketId')
                        tick = self.ticket_manager.find_ticket_by_id(ticket_id)
                        if not tick:
                            pass
                        else:
                            won_data = ticket.get('wonData')
                            if not won_data:
                                t = await self.ticket_manager.find_ticket(self.ticket_manager.active_game_id,
                                                                          self.ticket_manager.active_ticket_key)
                                print(t)
                                #await self.ticket_manager.resolve_ticket(t)
                                #logger.warning('%r %r Resending lost ticket %r', self.provider, self, ticket)
                                return
                else:
                    for ticket in body:
                        won_data = ticket.get('wonData')
                        if won_data:
                            ticket_status = ticket.get('status')
                            if ticket_status == 'PAIDOUT':
                                ticket_id = ticket.get('ticketId')
                                tick = self.ticket_manager.find_ticket_by_id(ticket_id)
                                if tick:
                                    tick.ticket_status = ticket_status
                                    tick.time_paid = ticket.get('timePaid', '')
                                    tick.time_resolved = ticket.get('timeResolved', '')
                                    tick.db_ticket.payment_data = won_data
                                    tick.db_ticket.ticket_status = ticket_status
                                    tick.on_pay()
                                    won_amount = won_data.get('wonAmount')
                                    won_jackpot = won_data.get('wonJackpot')
                                    tick.db_ticket.won_data = {'won': won_amount, 'stake': tick.stake, 'wonJackpot': won_jackpot}
                                    await tick.save()
                                    body = {tick.db_ticket.ticket_key: {
                                        'data': {
                                            'player': tick.db_ticket.live_session.data,
                                            'status': tick.db_ticket.status,
                                            'ticket_id': tick.db_ticket.ticket_id,
                                            'ticket_key': tick.db_ticket.ticket_key,
                                            'ticket_status': tick.db_ticket.ticket_status,
                                            'won_data': tick.db_ticket.won_data,
                                            'time_created': tick.db_ticket.time_created.isoformat()
                                        },
                                        'ticket': tick.db_ticket.details}}
                                    for session_key in self.ws_sessions.keys():
                                        self.provider.send_to_session(self.username, session_key, "ticket_resolve", body)
                                        body2 = {}
                                        live_session = self.get_live_session(tick.live_session_id)
                                        body2[tick.live_session_id] = {
                                            'sessionId': live_session.session_id,
                                            'accountId': live_session.account.account_id,
                                            'demo': live_session.account.demo,
                                            'player': live_session.player.name,
                                            'competitions': live_session.competitions,
                                            'target_amount': live_session.target_amount,
                                            'stake': live_session.stake,
                                            'won': live_session.won
                                        }
                                        self.provider.send_to_session(self.username, session_key, "sessions_update", body2)
                                    logger.info('[%d] %r [%s:%d:%d] Won : %f Jackpot: %f', tick.game_id, self,
                                                tick.player, tick.live_session_id, tick.ticket_key,
                                                won_amount, won_jackpot)
                                    tick.status = TicketStatus.DISCARD

    # Sockets configuration
    async def create_stream(self, stream_id: int, reuse: bool = True):
        return self.provider.sock_manager.add_user_socket(self.user_id, stream_id, reuse)

    async def stream_online(self, stream_id: int):
        if stream_id == 0:
            if self.competitions:
                logger.info('%r Resuming competitions %s', self, str(self.competitions))
                for competition in self.competitions.values():
                    if competition.status == competition.SLEEPING:
                        await competition.resume()
            else:
                body = self.resource_playlists(list(self.provider.competitions))
                self.send(Resource.PLAYLISTS, body, socket_id=stream_id)
        else:
            competition = self.get_competition(stream_id)
            if competition:
                if competition.status == competition.SLEEPING:
                    await competition.resume()
                else:
                    competition.online = True
            else:
                await self.ticket_manager.stream_online(stream_id)

    async def stream_lost(self, stream_id: int):
        if stream_id == 0:
            for competition_id, competition in self.competitions.items():
                if competition_id not in self.sockets and competition.status == competition.RUNNING:
                    competition.status = competition.SLEEPING
        else:
            competition = self.get_competition(stream_id)
            if competition:
                competition.status = competition.SLEEPING
            else:
                await self.ticket_manager.stream_lost(stream_id)

    async def stream_offline(self, stream_id: int):
        competition = self.get_competition(stream_id)
        if competition:
            competition.online = False
            for competition in self.competitions.values():
                if competition.online:  # or competition.lost:
                    return
            if not self.ticket_manager.sockets:
                self.close_event.set()
            else:
                self.ticket_manager.exit()

    # Tickets
    async def register_ticket(self, ticket: Ticket):
        await self.ticket_manager.register_ticket(ticket)
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
        asyncio.create_task(self.send_ticket_session(body))

    async def send_ticket_session(self, ticket_data: Dict):
        for session_key in self.ws_sessions:
            self.provider.send_to_session(self.username, session_key, 'ticket', ticket_data)

    def tickets_complete(self, game_id: int, live_session_id: int):
        live_session = self.get_live_session(live_session_id)
        ticket_map = live_session.ticket_maps.get(game_id)
        if all(ticket_map.values()):
            live_session.play_events.get(game_id).set()
        # print(f"Releasing lock {live_session_id} {game_id}")
            if live_session.event_lock.locked():
                live_session.event_lock.release()

    async def reset_competition_tickets(self, game_id: int):
        await self.ticket_manager.reset_competition_tickets(game_id)

    async def validate_competition_tickets(self, game_id: int):
        await self.ticket_manager.validate_competition_tickets(game_id)

    async def resolved_competition_ticket(self, ticket: Ticket):
        l_v = self.get_live_session(ticket.live_session_id)
        if l_v:
            l_v.stake += ticket.stake
            l_v.won += ticket.total_won
        if ticket.demo:
            if ticket.total_won > 0:
                ticket.ticket_status = 'PAIDOUT'
                ticket.db_ticket.won_data = {'won': ticket.total_won, 'stake': ticket.stake}
            else:
                ticket.ticket_status = 'LOST'
                ticket.db_ticket.won_data = {'won': ticket.total_won, 'stake': ticket.stake}
            await ticket.save()
            ticket.status = TicketStatus.DISCARD
        else:
            if ticket.total_won > 0:
                ticket.ticket_status = 'WON'
                ticket.db_ticket.won_data = {'won': ticket.total_won, 'stake': ticket.stake}
                await  ticket.save()
                payload = self.resource_ticket_by_id(1, ticket.ticket_id)
                socket = await self.ticket_manager.get_available_socket()
                socket, xs = self.send(Resource.TICKETS_FIND_BY_ID, payload,
                                       socket_id=socket.socket_id)
                logger.warning('%r Please validate ticket %d %f xs : %d',
                               self, ticket.ticket_id, ticket.total_won, xs)
            else:
                ticket.ticket_status = 'LOST'
                ticket.on_lost()
                await ticket.save()
                ticket.status = TicketStatus.DISCARD
        competition = self.get_competition(ticket.game_id)
        if competition:
            await competition.on_ticket_resolve(ticket)

    # Getters
    def get_competition(self, competition_id: int) -> Optional[LeagueCompetition]:
        return self.competitions.get(competition_id)

    def get_live_session(self, live_session_id: int) -> Optional[LiveSession]:
        return self.live_sessions.get(live_session_id)

    def get_socket(self, socket_id: int):
        return self.provider.sock_manager.get_socket(socket_id)

    # Payloads
    async def wss_account_data(self):
        return {
            'info': {
                'balance': f'{await self.account_manager.credit:.2f}',
                'demo': f'{await self.account_manager.demo_credit:.2f}',
                'jackpot': f'{self.account_manager.jackpot_value}',
                'jackpotAmount': f'{self.account_manager.jackpot_amount}'
            }
        }

    async def wss_providers_data(self):
        providers = {}
        for competition_id, competition in self.competitions.items():
            competition_data = await competition.wss_login_data()
            providers[competition_id] = competition_data
        return providers

    async def wss_user_data(self):
        return {
            'username': self.username,
            'userId': self.user_id
        }

    async def wss_session_data(self):
        body = {}
        for live_session_id, live_session in self.live_sessions.items():
            if live_session.status == live_session.SLEEPING:
                continue
            body[live_session_id] = {
                'sessionId': live_session_id,
                'accountId': live_session.account.account_id,
                'demo': live_session.account.demo,
                'player': live_session.player.name,
                'competitions': live_session.competitions,
                'target_amount': live_session.target_amount,
                'stake': live_session.stake,
                'won': live_session.won
            }
        return body

    async def wss_login_data(self):
        return {
            'success': True,
            'body': {
                'user': await self.wss_user_data(),
                'account': await self.wss_account_data(),
                'competitions': await self.wss_providers_data(),
                'sessions': await self.wss_session_data(),
                'tickets': await self.wss_tickets_data(0, 20)
            }
        }

    async def wss_tickets_data(self, ticket_key: int, n: int):
        return await load_tickets(self.provider, self.db_provider, self.db_user, ticket_key, n)

    # API
    def create_competition(self, game_id: int, mode: str, participants: List[Dict]) -> LeagueCompetition:
        competition = LeagueCompetition(self, game_id, mode, participants)
        self.competitions[game_id] = competition
        competition.init()
        return competition

    async def create_live_session(self, player_name: str, competition_data: Dict, account_data: Dict) -> LiveSession:
        session = await create_live_session(self.db_user, self.db_provider, player_name, competition_data, account_data)
        live_session = LiveSession(self, session, competition_data, account_data)
        for competition_id in competition_data:
            competition = self.get_competition(competition_id)
            if competition:
                competition.register_session(live_session)
        self.live_sessions[live_session.session_id] = live_session
        live_session.set_player(player_name)
        return live_session

    async def stop_live_session(self, live_session_id):
        live_session = self.get_live_session(live_session_id)
        if live_session:
            live_session.stop()

    async def restore_live_sessions(self):
        await load_active_tickets(self.provider, self.db_user, self.db_provider)

    async def sync_sessions(self):
        for session_key in self.ws_sessions:
            body = {
                'account': await self.wss_account_data(),
                'sessions': await self.wss_session_data()
            }
            self.provider.send_to_session(self.username, session_key, "account_info", body)

    async def close_ws_sessions(self):
        for session_key in self.ws_sessions:
            body = {
            }
            self.provider.send_to_session(self.username, session_key, "exit", body)

    def add_ws_session(self, session_key: str, session_data: Dict):
        channel_name = session_data.get('channel_name')
        self.ws_sessions[session_key] = WsSession(self, session_key, channel_name)

    def remove_ws_session(self, session_key) -> bool:
        try:
            self.ws_sessions.pop(session_key)
            return True
        except KeyError:
            return False

    def send(self, resource: str, body: Dict,
             socket_id: Optional[int] = None,
             stream_id: Optional[int] = None,
             method: str = 'GET') -> Tuple[int, int]:
        if not socket_id:
            t_socket_id = stream_id
        else:
            t_socket_id = socket_id
        xs, socket_id = self.provider.sock_manager.send(self.user_id, resource, body, socket_id=t_socket_id,
                                                        method=method)
        if socket_id > -1:
            self.msg_map[f'{socket_id}_{xs}'] = t_socket_id
        return socket_id, xs

    async def receive(self, socket_id: int, xs: int, resource: str, valid_response: bool, body: Union[List, Dict]):
        # pylint: disable=broad-except
        try:
            t_socket_id = self.msg_map.pop(f'{socket_id}_{xs}')
            if resource == Resource.LOGIN:
                await self.login_callback(socket_id, valid_response, body)
            elif resource == Resource.PLAYLISTS:
                await self.playlists_callback(valid_response, body)
            elif resource == Resource.SYNC:
                await self.sync_callback(valid_response, body)
            elif resource == Resource.TICKETS:
                await self.ticket_callback(socket_id, xs, valid_response, body)
            elif resource == Resource.TICKETS_FIND_BY_ID:
                await self.tickets_find_by_id_callback(xs, valid_response, body)
            else:
                competition = self.get_competition(t_socket_id)
                if competition:
                    await competition.receive(valid_response, resource, body)
        except Exception:
            logger.error('%r User receive (resource= %s, valid_response=%s) %s \n %s', self, resource,
                         valid_response, str(body), traceback.format_exc())

    def get_competition_results(self, game_id: int) -> Tuple[Dict, Dict]:
        competition = self.get_competition(game_id)
        if competition:
            return competition.get_ticket_validation_data()
        return {}, {}

    async def wait_closed(self):
        await self.close_ws_sessions()
        # for competition_id, competition in self.competitions.items():
        #    asyncio.create_task(competition.exit())
        # await self.close_event.wait()

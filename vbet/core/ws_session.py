from __future__ import annotations
import traceback
from typing import Dict, TYPE_CHECKING

from vbet.utils.log import get_logger

if TYPE_CHECKING:
    from vbet.game.user import User

logger = get_logger('ws-session')

SUDO_URI = {
    'exit' : 'application',
    'add'  : 'manager',
    'login': 'manager',
    'check': 'manager'
}

CLIENT_URI = {'player': 'manager'}


class WsSession:
    def __init__(self, user: User, session_key: str, channel_name: str):
        self.user: User = user
        self.channel_name: str = channel_name
        self.session_key: str = session_key

    async def auth_uri(self, body: Dict):
        try:
            data = await self.user.wss_login_data()
            self.user.provider.send_to_session(self.user.username, self.session_key, 'init', data)
            logger.info('User online %s', self.session_key)
        except Exception:
            logger.error(traceback.print_exc())

    async def deauth_uri(self, body: Dict):
        try:
            self.user.ws_sessions.pop(self.session_key)
        except KeyError:
            pass
        else:
            logger.info('User offline %s', self.session_key)

    async def tickets_uri(self, body: Dict):
        try:
            n = body.get('n')
            n = 10 if n < 10 else n
            n = 10 if n > 10 else n
            data = await self.user.wss_tickets_data(body.get("ticket_key"), n)
            self.user.provider.send_to_session(self.user.username, self.session_key, 'tickets', data)
        except Exception:
            logger.error(traceback.print_exc())

    async def create_session_uri(self, body: Dict):
        try:
            account = body.get('account')
            account_id = account.get('account_id')
            auto_start = body.get('auto_start', False)
            comps = body.get('competitions')
            comps = {int(k): v for k, v in comps.items()}
            demo = body.get('demo')
            target_amount = body.get('target_amount')
            player_config = body.get('player')
            player = player_config.get('name')  # type: str
            live_session = await self.user.create_live_session(player.lower(), comps, {
                'demo': demo,
                'account_id': account_id,
                'target_amount': target_amount,
                'options': {
                    'stake': 5,
                    'profit': 0,
                    'initial_token': 5,
                    'percent_value': 0.05
                }
            })
            if auto_start:
                live_session.start()
            data = {
                'status': True,
            }
            d = {live_session.session_id: {
                'sessionId': live_session.session_id,
                'accountId': live_session.account.account_id,
                'demo': live_session.account.demo,
                'player': live_session.player.name,
                'competitions': live_session.competitions,
                'target_amount': live_session.target_amount,
                'stake': live_session.stake,
                'won': live_session.won
            }}
            data.update(d[live_session.session_id])
            self.user.provider.send_to_session(self.user.username, self.session_key, "sessions_update", d)
            self.user.provider.send_to_session(self.user.username, self.session_key, 'create_session', data)
        except Exception:
            logger.error(traceback.print_exc())

    async def sessions_action_uri(self, body: Dict):
        try:
            action = body.get('action')
            if action == "stop":
                await self.user.stop_live_session(body.get('session_id'))
        except Exception:
            logger.error(traceback.print_exc())


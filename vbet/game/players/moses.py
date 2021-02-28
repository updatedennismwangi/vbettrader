from typing import Dict
import operator
import secrets
from collections import Counter

from vbet.game.tickets import Bet, Event, Ticket
from vbet.utils.log import get_logger, async_exception_logger
from vbet.utils.parser import encode_week, encode_team, g_map
from vbet.game.players.base import Player
from vbet.game.table import LeagueTable
from vbet.core import settings
import numpy

NAME = 'moses'

logger = get_logger(NAME)


class CustomPlayer(Player):

    def __init__(self, **kwargs):
        super().__init__(NAME, **kwargs)
        self.game_hash = {key: {} for key in self.live_session.competitions.keys()}
        self.min_loss_draw = 3
        self.target_team = 'VIL'
        self.dembele = tf.keras.models.load_model(f'{settings.DATA_DIR}/models/dembele')

    async def forecast(self, competition_id, active_week: int):
        competition = self.live_session.user.get_competition(competition_id)
        league_games = competition.league_games  # type: Dict[int, Dict]
        game_data = self.game_hash.get(competition_id, {})
        target_games = {}
        week_games = league_games.get(active_week)  # type: Dict[int, Dict]
        # week_stats = competition.table.get_week_stats(active_week)
        for event_id, event_data in week_games.items():
            player_a = event_data.get('A'
                                      '')
            # player_b = event_data.get('B')
            # event_stats = week_stats.get(event_id)
            if player_a == self.target_team:
                t = competition.table
                t_info = t.ready_table.get(event_data.get('A'))
                r_info = t.ready_table.get(event_data.get('B'))
                d_config = []
                d_config.extend(encode_week(active_week))
                d_config.extend(encode_team(event_data.get('B')))
                d_config.extend([t_info.get('points') / 114, r_info.get('points') / 114])
                payload = {'prev': {}, 'data': d_config}
                tt = LeagueTable(max_week=38)
                tt.setup_league(competition.league)
                for uu in range(1, active_week - 5):
                    eid = competition.get_block_by_week(uu)
                    tt.feed_result(eid, competition.league, uu, t.get_week_results(uu), {}, {})
                for x in range(int(active_week) - 5, active_week):
                    w_data = t.get_week_results(x)
                    eid = competition.get_block_by_week(x)
                    for e_id, e_data in w_data.items():
                        if e_data.get('A') == self.target_team:
                            sc = e_data.get('score')
                            rr = tt.ready_table.get(self.target_team).get('points')
                            vv = tt.ready_table.get(e_data.get('B')).get('points')
                            kk = [0, 1, rr / 114, vv / 114]
                            kk.extend(encode_team(e_data.get('B')))
                            kk.extend(g_map.get(sc[0]))
                            kk.extend(g_map.get(sc[1]))
                            payload['prev'][x] = kk
                            break
                        elif e_data.get('B') == self.target_team:
                            sc = e_data.get('score')
                            rr = tt.ready_table.get(self.target_team).get('points')
                            vv = tt.ready_table.get(e_data.get('A')).get('points')
                            kk = [1, 0, rr / 114, vv / 114]
                            kk.extend(encode_team(e_data.get('A')))
                            kk.extend(g_map.get(sc[1]))
                            kk.extend(g_map.get(sc[0]))
                            payload['prev'][x] = kk
                            break
                    tt.feed_result(eid, competition.league, x, w_data, {}, {})
                prev = payload.get('prev')
                d_config = payload.get('data', [])
                l_pool = d_config
                for l_w, d in prev.items():
                    l_pool.extend(d)
                print(l_pool)
                l = numpy.array([l_pool])
                kk = l.shape
                time_step = 1
                x = l.reshape([kk[0], kk[1], time_step])
                r = self.dembele.predict_classes(x)
                print(r)
                odd_id = 74
                target_games[event_id] = ({"odd_id": odd_id})
                break

        tickets = []
        for event_id, event_config in target_games.items():
            odd_id = event_config.get('odd_id')
            ticket = Ticket(competition.competition_id, self.name)
            event_data = week_games.get(event_id)
            participants = event_data.get('participants')
            odds = event_data.get('odds')
            event = Event(event_id, competition.league, active_week, participants)
            ticket.add_event(event)
            market_id, odd_name, odd_index = Player.get_market_info(str(odd_id))
            odd_value = float(odds[odd_index])
            bet = Bet(odd_id, market_id, odd_value, odd_name, 0)
            event.add_bet(bet)
            stake = await self.live_session.account.get_stake(odd_value=odd_value)
            total_odd = 1
            for event in ticket.events:
                for bet in event.bets:
                    bet.stake = stake
                    total_odd *= bet.odd_value
            win = round(stake * total_odd, 2)
            min_win = win
            max_win = win
            ticket._stake = stake
            ticket._min_winning = min_win
            ticket._max_winning = max_win
            ticket._total_won = 0
            ticket._grouping = 1
            ticket._winning_count = 1
            ticket._system_count = 1
            tickets.append(ticket)
        return tickets

    async def on_new_league(self, competition_id: int):
        self.game_map[competition_id] = True
        self.game_hash[competition_id] = {}

    def get_required_weeks(self, competition_id: int):
        competition = self.live_session.user.get_competition(competition_id)
        required_weeks = self.required_map.get(competition_id, [])
        required_weeks.clear()
        y = [x for x in range(11, competition.max_week + 1)]
        required_weeks.extend(y)

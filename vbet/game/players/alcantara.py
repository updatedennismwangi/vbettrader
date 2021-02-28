import asyncio
from typing import Dict, List, Tuple
import operator
import sys
import secrets
from vbet.game.tickets import Bet, Event, Ticket
from vbet.utils.log import get_logger, async_exception_logger
from .base import Player
from collections import Counter
import json

NAME = 'alcantara'

logger = get_logger(NAME)


class CustomPlayer(Player):

    def __init__(self, **kwargs):
        super().__init__(NAME, **kwargs)
        self.shutdown_event.set()
        self.game_hash = {key: {} for key in self.live_session.competitions.keys()}

    @async_exception_logger('forecast')
    async def forecast(self, competition_id, active_week: int):
        competition = self.live_session.user.get_competition(competition_id)
        league_games = competition.league_games  # type: Dict[int, Dict]
        week_games = league_games.get(active_week)  # type: Dict[int, Dict]
        week_stats = competition.table.get_week_stats(active_week)
        game_data = self.game_hash.get(competition_id, {})
        if not game_data:
            table = competition.table.table  # type: List[Dict]
            raw_table = competition.table.ready_table  # type: Dict[str, Dict]
            for event_id, event_data in week_games.items():
                odds = event_data.get('odds')
                player_a = event_data.get('A')
                player_b = event_data.get('B')
                team_a_d = raw_table.get(player_a)
                team_b_d = raw_table.get(player_b)
                team_a_pos = team_a_d.get('pos')
                team_b_pos = team_b_d.get('pos')
                last_week = league_games.get(active_week - 1)  # type: Dict[int, Dict]
                if team_a_pos in range(1, 5) and team_b_pos in range(10, 15):
                    x_flag = False
                    y_flag = False
                    for e_id, e_data in last_week.items():
                        pl_a = e_data.get('A')
                        pl_b = e_data.get('B')
                        if pl_a == player_a or pl_b == player_a:
                            opponent = pl_b if pl_a == player_a else pl_b
                            op_data = raw_table.get(opponent)
                            op_pos = op_data.get('pos')
                            if op_pos < team_a_pos:
                                r = competition.table.get_week_results(active_week - 1)
                                e_d = r.get(e_id)
                                score = e_d.get('score')
                                t_a_g, t_b_g = score[0], score[1]
                                if pl_a == player_a:
                                    if (t_a_g - t_b_g) > 2:
                                        x_flag = True
                                        print(e_d)
                                else:
                                    if (t_b_g - t_a_g) > 2:
                                        x_flag = True
                                        print(e_d)
                        elif pl_a == player_b or pl_b == player_b:
                            opponent = pl_b if pl_a == player_b else pl_b
                            op_data = raw_table.get(opponent)
                            op_pos = op_data.get('pos')
                            if op_pos > team_b_pos:
                                r = competition.table.get_week_results(active_week - 1)
                                e_d = r.get(e_id)
                                score = e_d.get('score')
                                t_a_g, t_b_g = score[0], score[1]
                                if pl_a == player_b:
                                    if (t_b_g - t_a_g) > 2:
                                        print(e_d)
                                        y_flag = True
                                else:
                                    if (t_a_g - t_b_g) > 2:
                                        print(e_d)
                                        y_flag = True
                    if x_flag or y_flag:
                        print(x_flag, y_flag)
                        game_data['team'] = player_a
                        break
                elif team_b_pos in range(1, 7) and team_a_pos in range(10, 17):
                    pass
                    """                    
                    x_flag = False
                    y_flag = False
                    for e_id, e_data in last_week.items():
                        pl_a = e_data.get('A')
                        pl_b = e_data.get('B')
                        if pl_a == player_b or pl_b == player_b:
                            opponent = pl_b if pl_a == player_b else pl_b
                            op_data = raw_table.get(opponent)
                            op_pos = op_data.get('pos')
                            if op_pos < team_b_pos:
                                r = competition.table.get_week_results(active_week - 1)
                                e_d = r.get(e_id)
                                score = e_d.get('score')
                                t_a_g, t_b_g = score[0], score[1]
                                if pl_a == player_b:
                                    if (t_a_g - t_b_g) > 1:
                                        x_flag = True
                                        print(e_d)
                                else:
                                    if (t_b_g - t_a_g) > 1:
                                        x_flag = True
                                        print(e_d)
                        elif pl_a == player_a or pl_b == player_a:
                            opponent = pl_b if pl_a == player_a else pl_b
                            op_data = raw_table.get(opponent)
                            op_pos = op_data.get('pos')
                            if op_pos > team_b_pos:
                                r = competition.table.get_week_results(active_week - 1)
                                e_d = r.get(e_id)
                                score = e_d.get('score')
                                t_a_g, t_b_g = score[0], score[1]
                                if pl_a == player_a:
                                    if (t_a_g - t_b_g) > 1:
                                        print(e_d)
                                        y_flag = True
                                else:
                                    if (t_b_g - t_a_g) > 1:
                                        print(e_d)
                                        y_flag = True
                    if x_flag or y_flag:
                        print(x_flag, y_flag)
                        game_data['team'] = player_a
                        break
                    """
                else:
                    continue

        if not game_data:
            return []
        team = game_data.get('team')
        ticket = Ticket(competition.competition_id, self.name)
        for event_id, event_data in week_games.items():
            odds = event_data.get('odds')
            player_a = event_data.get('A')
            player_b = event_data.get('B')
            if player_a == team or player_b == team:
                if player_a == team:
                    odd_id = 0
                else:
                    odd_id = 1
                participants = event_data.get('participants')
                event = Event(event_id, competition.league, active_week, participants)
                ticket.add_event(event)
                market_id, odd_name, odd_index = Player.get_market_info(str(odd_id))
                odd_value = float(odds[odd_index])
                bet = Bet(odd_id, market_id, odd_value, odd_name, 0)
                event.add_bet(bet)
                break
            else:
                continue

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
        return [ticket]

    async def on_new_league(self, competition_id: int):
        self.game_map[competition_id] = True
        self.game_hash[competition_id] = {}

    async def on_ticket_resolve(self, ticket: Ticket):
        game_data = self.game_hash.get(ticket.game_id, {})
        game_data.clear()

    def get_required_weeks(self, competition_id: int):
        competition = self.live_session.user.get_competition(competition_id)
        required_weeks = self.required_map.get(competition_id, [])
        required_weeks.clear()
        w = list(range(11, competition.max_week + 1))
        required_weeks.extend(w)

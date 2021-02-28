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

NAME = 'mbappe'

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
            team_data = table[0]
            team = team_data.get('team')
            streak = team_data.get('streak')
            l_week = streak.get(active_week - 1)
            n_week = streak.get(active_week + 1)
            ll_week = streak.get(active_week - 2)
            nn_week = streak.get(active_week + 2)
            if sum([l_week, n_week, ll_week, nn_week]) == 12:
                print(team, streak)
                game_data['team'] = team
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
                if odd_value > 2.5:
                    if odd_id == 0:
                        odd_id = 14
                    else:
                        odd_id = 12
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

    def get_required_weeks(self, competition_id: int):
        competition = self.live_session.user.get_competition(competition_id)
        required_weeks = self.required_map.get(competition_id, [])
        required_weeks.clear()
        # w = secrets.SystemRandom().choices(range(1, competition.max_week + 1), k=5)
        w = [3 + secrets.randbelow(competition.max_week - 6)]
        required_weeks.extend(w)

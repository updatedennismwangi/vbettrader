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

NAME = 'dest'

logger = get_logger(NAME)


class CustomPlayer(Player):

    def __init__(self, **kwargs):
        super().__init__(NAME, **kwargs)
        self.shutdown_event.set()
        self.game_hash = {key: {} for key in self.live_session.competitions.keys()}
        self.last_games = 0

    @async_exception_logger('forecast')
    async def forecast(self, competition_id, active_week: int):
        competition = self.live_session.user.get_competition(competition_id)
        league_games = competition.league_games  # type: Dict[int, Dict]
        week_games = league_games.get(active_week)  # type: Dict[int, Dict]
        week_stats = competition.table.get_week_stats(active_week)
        game_data = self.game_hash.get(competition_id, {})
        if not game_data:
            for team_data in competition.table.table:
                streak = team_data.get('streak')
                if team_data.get('team') not in [
                    "BAR",  # 14036
                    "LIV",  # 14045
                    "BMU",  # 41047
                    "JUV",  # 14045
                    "MAT"]:  # 14050
                    continue
                for event_id, event_data in week_games.items():
                    odds = event_data.get('odds')
                    player_a = event_data.get('A')
                    player_b = event_data.get('B')
                    if player_a == team_data.get('team') or player_b == team_data.get('team'):
                        chunk = [streak.get(v) for v in range(active_week-self.last_games, active_week)]
                        if None in chunk:
                            break
                        c = Counter(chunk)
                        # x = c.get('x', 0)
                        w = c.get(3, 0)
                        d = c.get(1, 0)
                        l = c.get(0, 0)
                        print(chunk)
                        if w == self.last_games:
                            game_data['team'] = team_data.get('team')
                            game_data['side'] = 1
        else:
            for event_id, event_data in week_games.items():
                player_a = event_data.get('A')
                player_b = event_data.get('B')
                if player_a == game_data.get('team') or player_b == game_data.get('team'):
                    if player_a != game_data.get('team'):
                        pass
                        # return []
        if not game_data:
            return []

        team = game_data.get('team')
        side = game_data.get('side')
        ticket = Ticket(competition.competition_id, self.name)
        for event_id, event_data in week_games.items():
            odds = event_data.get('odds')
            player_a = event_data.get('A')
            player_b = event_data.get('B')
            if player_a == team or player_b == team:
                """
                if player_a == team:
                    if side:
                        odd_id = 0
                    else:
                        odd_id = 1
                else:
                    if side:
                        odd_id = 1
                    else:
                        odd_id = 0
                """
                odd_id = 84
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
        if ticket.total_won > ticket.stake:
            game_data = self.game_hash.get(ticket.game_id, {})
            game_data.clear()

    def get_required_weeks(self, competition_id: int):
        competition = self.live_session.user.get_competition(competition_id)
        required_weeks = self.required_map.get(competition_id, [])
        required_weeks.clear()
        w = list(range(self.last_games + 1, competition.max_week + 1))
        required_weeks.extend(w)

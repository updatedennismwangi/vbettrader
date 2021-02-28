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

NAME = 'oscar'

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
            for team_data in table[0:3]:
                team = team_data.get('team')
                streak = Counter(list(team_data.get('streak').values()))
                x, y, z = streak.get(3, 0), streak.get(1, 0), streak.get(0, 0)
                # print(x, y, z)
                if z < 4:
                    ll = {}
                    required_weeks = self.required_map.get(competition_id)
                    for wk in required_weeks:
                        wk_games = league_games.get(wk)
                        for event_id, event_data in wk_games.items():
                            odds = event_data.get('odds')
                            player_a = event_data.get('A')
                            player_b = event_data.get('B')
                            if player_a == team or player_b == team:
                                if player_a == team:
                                    odd_id = 0
                                else:
                                    odd_id = 1
                                market_id, odd_name, odd_index = Player.get_market_info(str(odd_id))
                                odd_value = float(odds[odd_index])
                                ll[wk] = odd_value

                    if min(ll.values()) > 1.2:
                        game_data['team'] = team
                        # fp = open(f'{competition.competition_id}_{competition.league}_{active_week}')
                        # json.dump({'table': competition.table.table, 'data': [team, x, y, z, ll]})
                        print(team, x, y, z, ll)

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
        if ticket.total_won > ticket.stake:
            self.game_map[ticket.game_id] = False
            game_data = self.game_hash.get(ticket.game_id, {})
            game_data.clear()

    def get_required_weeks(self, competition_id: int):
        competition = self.live_session.user.get_competition(competition_id)
        required_weeks = self.required_map.get(competition_id, [])
        required_weeks.clear()
        # w = secrets.SystemRandom().choices(range(1, competition.max_week + 1), k=5)
        w = [secrets.randbelow(competition.max_week + 1)]
        required_weeks.extend(w)

import asyncio
from typing import Dict, List, Tuple
import operator
import sys
import secrets
from vbet.game.tickets import Bet, Event, Ticket
from vbet.utils.log import get_logger, async_exception_logger
from .base import Player
from collections import Counter

NAME = 'haaland'

logger = get_logger(NAME)


class CustomPlayer(Player):

    def __init__(self, **kwargs):
        super().__init__(NAME, **kwargs)
        self.team = None
        self.shutdown_event.set()
        self.game_hash = {key: {} for key in self.live_session.competitions.keys()}
        self.odd_id = 2

    @staticmethod
    def get_indexes(weeks):
        m = []
        for x in weeks:
            for y in weeks:
                if x == y:
                    continue
                if (x, y) in m or (y, x) in m:
                    continue
                m.append((x, y))
        return m

    @async_exception_logger('forecast')
    async def forecast(self, competition_id, active_week: int):
        competition = self.live_session.user.get_competition(competition_id)
        league_games = competition.league_games  # type: Dict[int, Dict]
        week_games = league_games.get(active_week)  # type: Dict[int, Dict]
        # week_stats = competition.table.get_week_stats(active_week)
        weeks = secrets.SystemRandom().sample(list(week_games.keys()), k=5)
        matches = self.get_indexes(weeks)
        print(matches)
        tickets = []
        for k_match in matches:
            ticket = Ticket(competition.competition_id, self.name)
            for event_id in k_match:
                event_data = week_games.get(event_id)
                odds = event_data.get('odds')
                participants = event_data.get('participants')
                event = Event(event_id, competition.league, active_week, participants)
                ticket.add_event(event)
                market_id, odd_name, odd_index = Player.get_market_info(str(self.odd_id))
                odd_value = float(odds[odd_index])
                bet = Bet(self.odd_id, market_id, odd_value, odd_name, 0)
                event.add_bet(bet)
            stake = 0
            total_odd = 1
            for event in ticket.events:
                for bet in event.bets:
                    bet.stake = stake
                    total_odd *= bet.odd_value
            win = round(stake * total_odd, 2)
            stake = await self.live_session.account.get_stake(odd_value=total_odd)
            min_win = win
            max_win = win
            ticket._stake = stake
            ticket._min_winning = min_win
            ticket._max_winning = max_win
            ticket._total_won = 0
            ticket._grouping = len(k_match)
            ticket._winning_count = 1
            ticket._system_count = 1
            tickets.append(ticket)
        print(len(tickets))
        return tickets

    async def on_new_league(self, competition_id: int):
        self.game_map[competition_id] = True
        self.game_hash[competition_id] = {}

    async def on_ticket_resolve(self, ticket: Ticket):
        game_data = self.game_hash.get(ticket.game_id, {})
        game_data.clear()
        # if ticket.total_won > ticket.stake:
        #    self.game_map[ticket.game_id] = False

    def get_required_weeks(self, competition_id: int):
        competition = self.live_session.user.get_competition(competition_id)
        required_weeks = self.required_map.get(competition_id, [])
        required_weeks.clear()
        required_weeks.extend(range(1, competition.max_week + 1))

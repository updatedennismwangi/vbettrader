import asyncio
from typing import Dict, List, Tuple
import operator
import sys
import secrets
from vbet.game.tickets import Bet, Event, Ticket
from vbet.utils.log import get_logger, async_exception_logger
from .base import Player
from collections import Counter

NAME = 'update'

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
        table = competition.table.table  # type: List[Dict]
        target_team = None
        target_market = None

        for team_data in table:
            team = team_data.get('team')
            streak = sorted(team_data.get('streak').items(), key=operator.itemgetter(0))
            back = streak[active_week-4:active_week - 1]
            future = streak[active_week:active_week + 3]
            back = [k[1] for k in back]
            future = [k[1] for k in future]
            al = back + future
            if len(al) < 5:
                continue
            aa = Counter(al)
            mm, nn, oo = aa.get(3, 0), aa.get(1, 0), aa.get(0, 0)
            if oo == 6:
                target_market = 0
            elif nn == 6:
                target_market = 1
            elif mm == 6:
                target_market = 3
            else:
                continue

            if target_market:
                for event_id, event_data in week_games.items():
                    player_a = event_data.get('A')
                    player_b = event_data.get('B')
                    event_stats = week_stats.get(event_id)
                    if player_a == team or player_b == team:
                        ii = 0 if player_a == team else 1
                        team_to_team = event_stats.get("teamToTeam")
                        head_to_head = team_to_team.get("headToHead")
                        u, v = self.pick_winner(head_to_head)
                        if u is not None and u != 2:
                            if ii == u and v > 1:
                                target_team = team
                            """
                            if u == 0 and ii == 0:
                                if target_market == 3:
                                    target_team = team
                            elif u == 1 and ii == 1:
                                if target_market == 3:
                                    target_team = team
                            """
                        break
                if target_team:
                    print(team, ii, u, v, active_week, back, future)
                    break

        if target_team is None:
            return []
        team = target_team
        ticket = Ticket(competition.competition_id, self.name)
        for event_id, event_data in week_games.items():
            odds = event_data.get('odds')
            player_a = event_data.get('A')
            player_b = event_data.get('B')
            if player_a == team or player_b == team:
                if player_a == team:
                    if target_market == 3:
                        odd_id = 0
                    elif target_market == 1:
                        odd_id = 2
                    else:
                        odd_id = 1
                else:
                    if target_market == 3:
                        odd_id = 1
                    elif target_market == 1:
                        odd_id = 2
                    else:
                        odd_id = 0
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

    def get_required_weeks(self, competition_id: int):
        competition = self.live_session.user.get_competition(competition_id)
        required_weeks = self.required_map.get(competition_id, [])
        required_weeks.clear()
        required_weeks.extend(range(4, competition.max_week + 1, 4))

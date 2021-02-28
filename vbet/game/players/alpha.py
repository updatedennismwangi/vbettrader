from typing import Dict
import operator
import secrets
import asyncio
from collections import Counter

from vbet.game.tickets import Bet, Event, Ticket
from vbet.utils.log import get_logger, async_exception_logger
from vbet.game.players.base import Player

NAME = 'alpha'


logger = get_logger(NAME)


class CustomPlayer(Player):

    def __init__(self, **kwargs):
        super().__init__(NAME, **kwargs)
        self.game_hash = {key: {} for key in self.live_session.competitions.keys()}
        self.match_future = 2
        self.match_past = 7
        self.game_queue: Dict[int, bool] = {}
        self.next_comp = 0
        self.round_map = []
        self.round_flag = False
        self.round_key = 0

    async def forecast(self, competition_id, active_week: int):
        competition = self.live_session.user.get_competition(competition_id)
        league_games = competition.league_games  # type: Dict[int, Dict]
        game_data = self.game_hash.get(competition_id, {})
        if not game_data:
            table = competition.table.table
            for top_player in table:
                streak = top_player.get('streak')
                t_streak = sorted(streak.items(), key=operator.itemgetter(0))
                f_streak = t_streak[active_week - (self.match_past + 1):active_week - 1]
                u_streak = [x[1] for x in f_streak if isinstance(x[1], int)]
                if len(u_streak) >= self.match_past:
                    if sum(u_streak) == 21:
                        v_streak = t_streak[active_week: active_week + self.match_future]
                        if len(v_streak) >= self.match_future:
                            logger.info('%r Possible event League : %d Week: %d', competition, competition.league,
                                        active_week)
                            game_data['team'] = top_player.get('team')
                            game_data['enabled'] = True
                            game_data['start_week'] = active_week
                            game_data['quiz'] = []
                            competition.extend_required_weeks(game_data.get('quiz'))
                            self.game_queue[competition_id] = True
                            competition.wait_event = True  # Disable competition
                            break
                break

        if not game_data:
            return []

        if not (len(self.game_queue) == len(self.game_hash)):
            return []

        if not self.round_flag:
            self.round_map = list(self.game_queue.keys())
            secrets.SystemRandom().shuffle(self.round_map)
            self.round_flag = True
            self.round_key = 0

        # print(self.game_hash, self.round_map, self.round_key)

        yy = self.round_map[self.round_key]
        if yy != competition_id:
            comp = self.live_session.user.get_competition(yy)
            comp.wait_event = False
            asyncio.ensure_future(comp.dispatch_events())
            return []

        self.game_queue[yy] = False
        competition.wait_event = False  # Enable competition
        game_data = self.game_hash.get(yy, {})
        target_games = {}
        target_team = game_data.get("team")
        week_games = league_games.get(active_week)  # type: Dict[int, Dict]
        for event_id, event_data in week_games.items():
            player_a = event_data.get('A')
            player_b = event_data.get('B')
            if player_a == target_team or player_b == target_team:
                if player_a == target_team:
                    odd_id = 0
                else:
                    odd_id = 1
                target_games[event_id] = ({"odd_id": odd_id})
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
        # print(competition, tickets)
        return tickets

    async def on_new_league(self, competition_id: int):
        self.game_map[competition_id] = True
        self.game_hash[competition_id] = {}

    async def on_ticket_resolve(self, ticket: Ticket):
        if ticket.total_won > ticket.stake:
            self.game_hash = {key: {} for key in self.live_session.competitions.keys()}
            self.round_key = 0
            self.round_flag = False
            self.game_queue.clear()
            self.game_map[ticket.game_id] = False
            self.game_hash[ticket.game_id].clear()
            for k, v in self.game_hash.items():
                competition = self.live_session.user.get_competition(k)
                competition.wait_event = False
                # competition.extend_required_weeks([v.get('start_week')])
                asyncio.ensure_future(competition.dispatch_events())

        else:
            competition = self.live_session.user.get_competition(ticket.game_id)
            competition.wait_event = True
            if self.round_key >= len(self.game_queue) - 1:
                secrets.SystemRandom().shuffle(self.round_map)
                self.round_flag = True
                self.round_key = 0
            self.round_key += 1
            yy = self.round_map[self.round_key]
            competition = self.live_session.user.get_competition(yy)
            competition.wait_event = False
            asyncio.ensure_future(competition.dispatch_events())

    def get_required_weeks(self, competition_id: int):
        competition = self.live_session.user.get_competition(competition_id)
        required_weeks = self.required_map.get(competition_id, [])
        required_weeks.clear()
        y = [x for x in range(11, competition.max_week + 1)]
        required_weeks.extend(y)

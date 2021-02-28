from typing import Dict
import operator
import secrets
from collections import Counter

from vbet.game.tickets import Bet, Event, Ticket
from vbet.utils.log import get_logger, async_exception_logger
from vbet.game.players.base import Player

NAME = 'darius'

logger = get_logger(NAME)


class CustomPlayer(Player):

    def __init__(self, **kwargs):
        super().__init__(NAME, **kwargs)
        self.game_hash = {key: {} for key in self.live_session.competitions.keys()}
        self.min_loss_draw = 3
        self.match_future = 6
        self.max_pos = 8

    async def forecast(self, competition_id, active_week: int):
        competition = self.live_session.user.get_competition(competition_id)
        league_games = competition.league_games  # type: Dict[int, Dict]
        game_data = self.game_hash.get(competition_id, {})
        if not game_data:
            table = competition.table.table.copy()
            for top_player in table[int(len(table) / 2):]:
                streak = top_player.get('streak')
                t_streak = sorted(streak.items(), key=operator.itemgetter(0))
                v_streak = t_streak[active_week: active_week + self.match_future]
                if len(v_streak) >= self.match_future:
                    a = []
                    for w, _ in v_streak:
                        week_matches = league_games.get(w)
                        e_p = None
                        for e_id, e_data in week_matches.items():
                            player_a = e_data.get('A')
                            player_b = e_data.get('B')
                            if player_a == top_player.get('team') or player_b == top_player.get('team'):
                                if player_a == top_player.get('team'):
                                    opponent = player_b
                                else:
                                    opponent = player_a
                                op_data = competition.table.ready_table.get(opponent)
                                pos = op_data.get('pos')
                                e_p = pos
                                break
                        if e_p > self.max_pos:
                            break
                        else:
                            a.append(e_p)
                    if len(a) != self.match_future:
                        break
                    else:
                        logger.info('%r Attempting match League : %d Week: %d %s', competition, competition.league,
                                    active_week, str(a))
                        game_data['team'] = top_player.get('team')
                        game_data['start_week'] = active_week
                        game_data['quiz'] = [_ for _ in range(active_week, active_week + self.match_future, 2)]
                        break
        if not game_data:
            return []
        target_games = {}
        target_team = game_data.get("team")
        week_games = league_games.get(active_week)  # type: Dict[int, Dict]
        for event_id, event_data in week_games.items():
            player_a = event_data.get('A')
            player_b = event_data.get('B')
            if player_a == target_team or player_b == target_team:
                if player_a == target_team:
                    odd_id = 1
                else:
                    odd_id = 0
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
        return tickets

    async def on_new_league(self, competition_id: int):
        self.game_map[competition_id] = True
        self.game_hash[competition_id] = {}

    async def on_ticket_resolve(self, ticket: Ticket):
        if ticket.total_won > ticket.stake:
            self.game_hash.get(ticket.game_id).clear()

    def get_required_weeks(self, competition_id: int):
        competition = self.live_session.user.get_competition(competition_id)
        required_weeks = self.required_map.get(competition_id, [])
        required_weeks.clear()
        y = [x for x in range(11, competition.max_week + 1)]
        required_weeks.extend(y)

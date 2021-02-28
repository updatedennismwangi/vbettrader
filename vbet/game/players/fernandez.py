from typing import Dict
import operator
import secrets
from collections import Counter

from vbet.game.tickets import Bet, Event, Ticket
from vbet.utils.log import get_logger, async_exception_logger
from vbet.game.players.base import Player

NAME = 'fernandez'

logger = get_logger(NAME)


class CustomPlayer(Player):

    def __init__(self, **kwargs):
        super().__init__(NAME, **kwargs)
        self.game_hash = {key: {} for key in self.live_session.competitions.keys()}
        self.min_loss_draw = 3

    async def forecast(self, competition_id, active_week: int):
        competition = self.live_session.user.get_competition(competition_id)
        league_games = competition.league_games  # type: Dict[int, Dict]
        game_data = self.game_hash.get(competition_id, {})
        if not game_data:
            table = competition.table.table.copy()
            for top_player in table[len(table) - 2:]:
                streak = top_player.get('streak')
                t_streak = sorted(streak.items(), key=operator.itemgetter(0))
                f_streak = t_streak[active_week - 6:active_week - 1]
                u_streak = [x[1] for x in f_streak if isinstance(x[1], int)]
                if len(u_streak) >= 5:
                    if sum(u_streak) < 1:
                        v_streak = t_streak[active_week: active_week + 9]
                        if len(v_streak) >= 9:
                            logger.info('%r Attempting match League : %d Week: %d', competition, competition.league,
                                        active_week)
                            game_data['team'] = top_player.get('team')
                            game_data['enabled'] = False
                            game_data['start_week'] = active_week
                            break
        if not game_data:
            return []
        enabled = game_data.get('enabled')
        if not enabled:
            return []
        target_games = {}
        target_team = game_data.get("team")
        week_games = league_games.get(active_week)  # type: Dict[int, Dict]
        week_stats = competition.table.get_week_stats(active_week)
        for event_id, event_data in week_games.items():
            player_a = event_data.get('A')
            player_b = event_data.get('B')
            event_stats = week_stats.get(event_id)
            if player_a == target_team or player_b == target_team:
                if player_a == target_team:
                    odd_id = 1
                else:
                    odd_id = 0
                team_to_team = event_stats.get("teamToTeam")
                head_to_head = team_to_team.get("headToHead")
                last_result = team_to_team.get("lastResult")
                performance = team_to_team.get("performance")
                u, v = self.pick_winner(head_to_head)
                aa, bb = self.pick_winner(head_to_head, True)
                home_r, away_r = self.get_result_ratio(last_result)
                print(odd_id, u, v, aa, bb, home_r, away_r)
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

    async def on_result(self, competition_id: int):
        game_data = self.game_hash.get(competition_id, {})
        competition = self.live_session.user.get_competition(competition_id)
        if game_data:
            team = game_data.get('team')
            start_week = game_data.get('start_week')
            team_data = competition.table.ready_table.get(team)
            streak = team_data.get('streak')
            t_streak = sorted(streak.items(), key=operator.itemgetter(0))
            v_streak = t_streak[start_week: start_week + 9]
            y = [k[1] for k in v_streak[0:self.min_loss_draw] if isinstance(k[1], int)]
            if len(y) >= self.min_loss_draw:
                h = Counter(y)
                if h.get(1, 0) < 1 and h.get(3, 0) < 1:
                    # Activate placing ticket
                    if not game_data['enabled']:
                        game_data['enabled'] = True
                    logger.info('%r Check League : %d Team: %s %s %s', competition, competition.league, team, str(y),
                                str(v_streak))
                else:
                    game_data.clear()

    def get_required_weeks(self, competition_id: int):
        competition = self.live_session.user.get_competition(competition_id)
        required_weeks = self.required_map.get(competition_id, [])
        required_weeks.clear()
        y = [x for x in range(10, competition.max_week + 1)]
        required_weeks.extend(y)

from typing import Dict
import operator
import secrets

from vbet.game.tickets import Bet, Event, Ticket
from vbet.utils.log import get_logger
from vbet.game.players.base import Player

NAME = 'felix'

logger = get_logger(NAME)


class CustomPlayer(Player):

    def __init__(self, **kwargs):
        super().__init__(NAME, **kwargs)
        self.game_hash = {key: {} for key in self.live_session.competitions.keys()}

    async def forecast(self, competition_id, active_week: int):
        competition = self.live_session.user.get_competition(competition_id)
        league_games = competition.league_games  # type: Dict[int, Dict]
        week_games = league_games.get(active_week)  # type: Dict[int, Dict]
        week_stats = competition.table.get_week_stats(active_week)
        game_data = self.game_hash.get(competition_id, {})
        if not game_data:
            for event_id, event_data in week_games.items():
                player_a = event_data.get('A')
                player_b = event_data.get('B')
                odds = event_data.get('odds')
                p_1 = competition.table.ready_table.get(player_a)
                p_2 = competition.table.ready_table.get(player_b)
                p_2_pos = p_2.get('pos')
                p_1_pos = p_1.get('pos')
                home = self.get_market('0', odds)
                away = self.get_market('1', odds)
                if p_1_pos > p_2_pos:
                    opponent = player_a
                    target = player_b
                else:
                    opponent = player_b
                    target = player_a
                home_away = 0 if opponent == player_b else 1
                event_stats = week_stats.get(event_id)
                team_to_team = event_stats.get("teamToTeam")
                head_to_head = team_to_team.get("headToHead")
                last_result = team_to_team.get("lastResult")
                performance = team_to_team.get("performance")
                u, v = self.pick_winner(head_to_head)
                aa, bb = self.pick_winner(head_to_head, True)
                home_r, away_r = self.get_result_ratio(last_result)
                target_r = home_r if home_away == 0 else away_r
                opponent_r = home_r if home_away == 1 else away_r
                aaa = self.pick_over(1.5, head_to_head)
                g = performance.get("g")
                odds = event_data.get('odds')
                odd_id = 13
                market_id, odd_name, odd_index = Player.get_market_info(str(odd_id))
                odd_value = float(odds[odd_index])
                if aaa and odd_value > 1.24:
                    if float(g[0]) > 1.7 and float(g[1]) > 1.5:
                        if aaa >= 5:
                            o_id = odd_id
                            match_data = {'odd_id': o_id}
                            game_data[event_id] = match_data
                            target_odd = home if home_away == 0 else away
                            opponent_odd = home if home_away == 1 else away
                            print(home_away, target, opponent, target_odd, opponent_odd, u, v, aa, bb, target_r,
                                  opponent_r, o_id)

        if not game_data:
            return []
        tickets = []
        for event_id, event_config in game_data.items():
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
        game_data = self.game_hash.get(ticket.game_id, {})
        game_data.clear()

    def get_required_weeks(self, competition_id: int):
        competition = self.live_session.user.get_competition(competition_id)
        required_weeks = self.required_map.get(competition_id, [])
        required_weeks.clear()
        required_weeks.extend(range(10, competition.max_week))

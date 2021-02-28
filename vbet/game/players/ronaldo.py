from typing import Dict
import operator
import secrets

from vbet.game.tickets import Bet, Event, Ticket
from vbet.utils.log import get_logger, async_exception_logger
from vbet.game.players.base import Player

NAME = 'ronaldo'

logger = get_logger(NAME)


class CustomPlayer(Player):

    def __init__(self, **kwargs):
        super().__init__(NAME, **kwargs)
        self.game_hash = {key: {} for key in self.live_session.competitions.keys()}

    @async_exception_logger('ronaldo')
    async def forecast(self, competition_id, active_week: int):
        competition = self.live_session.user.get_competition(competition_id)
        league_games = competition.league_games  # type: Dict[int, Dict]
        game_data = self.game_hash.get(competition_id, {})
        if not game_data:
            required_weeks = self.required_map.get(competition_id, [])
            table = competition.table.table.copy()
            table.reverse()
            for top_player in table:
                d = []
                e = {}
                f = {}
                for week in required_weeks:
                    last_week = top_player.get('streak')[week - 1]
                    next_week = top_player.get('streak')[week + 1]
                    if last_week > -1 and next_week > -1:
                        d.append((last_week, next_week))
                    else:
                        break
                if len(d) >= 5:
                    q = 0
                    for week in required_weeks:
                        games = league_games.get(week)  # type: Dict[int, Dict]
                        game_streak = d[q]
                        for event_id, event_data in games.items():
                            player_a = event_data.get('A')
                            player_b = event_data.get('B')
                            if player_a == top_player.get('team') or player_b == top_player.get('team'):
                                if player_a == top_player.get('team'):
                                    if game_streak[0] > 1 and game_streak[1] > 1:
                                        odd_id = 12
                                    elif game_streak[0] == 1 and game_streak[1] == 1:
                                        odd_id = 12
                                    else:
                                        odd_id = 1
                                else:
                                    if game_streak[0] > 1 and game_streak[1] > 1:
                                        odd_id = 14
                                    elif game_streak[0] == 1 and game_streak[1] == 1:
                                        odd_id = 14
                                    else:
                                        odd_id = 0
                                odds = event_data.get('odds')
                                market_id, odd_name, odd_index = Player.get_market_info(str(odd_id))
                                odd_value = float(odds[odd_index])
                                if odd_value > 1.2:
                                    f[week] = odd_id
                                    e[week] = odd_value
                                break
                        q += 1
                    if len(e) >= 5:
                        game_data['team'] = top_player.get('team')
                        uu = sorted(e.items(), key=operator.itemgetter(1))
                        game_data['pattern'] = uu
                        game_data['index'] = 0
                        game_data['odds'] = f
                break

        if not game_data:
            self.game_map[competition_id] = False
            return []

        pattern = game_data.get('pattern')
        index = game_data.get('index')
        odds_pool = game_data.get('odds')
        if index > len(pattern):
            return []
        game_data['index'] = index + 1
        ac_week = pattern[index][0]
        print(pattern, odds_pool, ac_week)

        target_games = {}
        target_team = game_data.get("team")
        week_games = league_games.get(ac_week)  # type: Dict[int, Dict]
        for event_id, event_data in week_games.items():
            player_a = event_data.get('A')
            player_b = event_data.get('B')
            if player_a == target_team or player_b == target_team:
                target_games[event_id] = ({"odd_id": odds_pool.get(ac_week)})
        tickets = []
        for event_id, event_config in target_games.items():
            odd_id = event_config.get('odd_id')
            ticket = Ticket(competition.competition_id, self.name)
            event_data = week_games.get(event_id)
            participants = event_data.get('participants')
            odds = event_data.get('odds')
            event = Event(event_id, competition.league, ac_week, participants)
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
            self.game_map[ticket.game_id] = False

    def get_required_weeks(self, competition_id: int):
        # competition = self.live_session.user.get_competition(competition_id)
        required_weeks = self.required_map.get(competition_id, [])
        required_weeks.clear()
        b = []
        while len(b) < 5:
            c = secrets.choice([2, 3, 4, 5, 6])
            b.append(c)
        y = []
        for i in range(1, len(b) + 1):
            y.append(2 + sum(b[0:i]))
        print(y)
        required_weeks.extend(y)

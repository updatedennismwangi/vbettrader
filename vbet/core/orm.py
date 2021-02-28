from asgiref.sync import sync_to_async
from typing import Dict, TYPE_CHECKING


if TYPE_CHECKING:
    from vbet.core.provider import Provider
    from vbet.core.socket_manager import Socket
    from vweb.vclient.models import User as UserAdmin, Providers, LiveSession as DbLiveSession

from vbet.utils.log import get_logger

logger = get_logger('orm')


def load_provider_data(name: str):
    from vweb.vclient.models import ProviderInstalled
    try:
        config = ProviderInstalled.objects.get(name=name)
    except ProviderInstalled.DoesNotExist:
        logger.warning('Provider %s db entry not found. Did you run configure ? ', name)
    else:
        return config


def get_provider_data(pk: int, name: str):
    from vbet.core.provider import Provider
    user = Provider.UserDb.objects.get(pk=pk)
    return user.providers.get(provider=name)


def create_live_session(db_user, db_provider, player_name: str, competition_data: Dict, account_data: Dict):
    from vweb.vclient.models import LiveSession
    session = LiveSession(user=db_user, provider=db_provider)
    session.status = 'paused'
    session.competitions = competition_data
    session.data = {'account': account_data}
    session.save()
    return session


def load_tickets(provider, db_p, user, ticket_key: int, n: int):
    if ticket_key == 0:
        last_ten = provider.TicketsDb.objects.filter(user=user).order_by('-ticket_key')[:n]
    else:
        last_ten = provider.TicketsDb.objects.filter(user=user,
                                                     ticket_key__lt=ticket_key).order_by('-ticket_key')[:n]
    body = {}
    for x in last_ten:
        body[x.ticket_key] = {
            'data': {
                'player': x.live_session.data,
                'status': x.status,
                'ticket_id': x.ticket_id,
                'ticket_key': x.ticket_key,
                'ticket_status': x.ticket_status,
                'won_data': x.won_data,
                'time_created': x.time_created.isoformat()
            },
            'ticket': x.details}
    return body


def on_start_live_session(db_live_session):
    db_live_session.status = "running"
    db_live_session.save()


def load_active_tickets(provider, db_user, db_provider):
    tickets = provider.TicketsDb.objects.filter(user=db_user, provider=db_provider, resolved=False)
    if tickets:
        for tick in tickets:
            # TODO: ACTIVE TICKETS
            pass
            # print(tick)


def save_user(user_id: int, username: str, provider, user_data: Dict):
    from vweb.vclient.models import Providers, User
    user = User.objects.get(pk=user_id)
    provider = Providers(username=username, provider=provider, token=user_data)
    provider.user = user
    provider.save()
    user.save()


def update_ticket(db_ticket):
    db_ticket.save()


def save_ticket(provider, db_user, db_provider, ticket) -> int:
    tick = provider.TicketsDb(user=db_user, provider=db_provider, live_session=ticket.db_live_session)
    tick.demo = ticket.demo
    tick.details = ticket.content
    tick.status = ticket.status
    tick.ticket_status = ticket.ticket_status
    tick.won_data = {'won': ticket.total_won, 'stake': ticket.stake}
    tick.save()
    ticket.db_ticket = tick
    return tick.ticket_key


load_provider_data = sync_to_async(load_provider_data, thread_sensitive=False)

get_provider_data = sync_to_async(get_provider_data, thread_sensitive=False)

create_live_session = sync_to_async(create_live_session, thread_sensitive=False)

load_tickets = sync_to_async(load_tickets, thread_sensitive=False)

on_start_live_session = sync_to_async(on_start_live_session, thread_sensitive=False)

save_user = sync_to_async(save_user, thread_sensitive=False)

save_ticket = sync_to_async(save_ticket, thread_sensitive=False)

update_ticket = sync_to_async(update_ticket, thread_sensitive=False)

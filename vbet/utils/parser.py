import json
import os
from datetime import datetime
from typing import Dict, Any, Tuple, Optional, Union, List
import aiofile

import pytz


def post_success(data: dict):
    return {'success': True, 'errors': {}, 'data': data}


def post_error(errors: dict):
    return {'success': False, 'errors': errors, 'data': {}}


def encode_json(data: Dict) -> str:
    return json.dumps(data)


def decode_json(data: Any) -> Union[Dict, List, None]:
    if isinstance(data, str):
        try:
            return json.loads(data)
        except ValueError:
            return None
    return None


def inspect_ws_server_payload(payload: Dict) -> Optional[Tuple[str, Dict]]:
    uri: Optional[str] = payload.get('uri', None)
    body: Optional[Any] = payload.get('body', None)
    if uri is not None and body is not None:
        return uri, body


def inspect_websocket_response(payload: Dict) -> Optional[Tuple[int, str, int, bool, Any]]:
    res: Dict = payload.get('res', {})
    xs: Optional[int] = payload.get('xs', None)
    status_code: Optional[int] = res.get('statusCode', None)
    valid_response: bool = res.get('validResponse', False)
    resource: Optional[str] = res.get('resource', None)
    body: Optional[Any] = res.get('body', None)
    _resource: Optional[str] = None
    for k, v in Resources.items():
        if v == resource:
            _resource = k
            break
    if _resource:
        _resource = resource
        return xs, _resource, status_code, valid_response, body


def get_ticket_timestamp() -> str:
    now = datetime.now(pytz.UTC).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]
    return "%s%s" % (now, "Z")


def create_dir(dir_name: str):
    os.makedirs(dir_name, exist_ok=True)


async def dump_data(path: str, username: str, competition_id: int, league_id: int, data: Dict):
    os.makedirs(f'{path}/{username}/{competition_id}', exist_ok=True)
    f = aiofile.AIOFile(f'{path}/{username}/{competition_id}/{league_id}.json', "w")
    await f.open()
    await f.write(encode_json(data))
    await f.close()


class Resource:
    LOGIN = '/session/login'
    SYNC = '/session/sync'
    EVENTS = '/eventBlocks/event/data'
    RESULTS = '/eventBlocks/event/result'
    TICKETS = '/tickets/send'
    HISTORY = '/eventBlocks/history'
    STATS = '/eventBlocks/stats'
    TICKETS_FIND_BY_ID = '/tickets/findById'
    PLAYLISTS = '/playlists/'


Resources = {
    'login': Resource.LOGIN,
    'sync': Resource.SYNC,
    'events': Resource.EVENTS,
    'results': Resource.RESULTS,
    'history': Resource.HISTORY,
    'tickets': Resource.TICKETS,
    'stats': Resource.STATS,
    'tickets_find_by_id': Resource.TICKETS_FIND_BY_ID,
    'playlists': Resource.PLAYLISTS
}


def map_resource_to_name(resource: str):
    return list(Resources.keys())[list(Resources.values()).index(resource)]


def iter_weeks_from(weeks: List, max_weeks: int = 5):
    week_count = len(weeks)
    weeks_p = min(week_count, max_weeks)
    while len(weeks) > weeks_p:
        block = weeks[:max_weeks]
        for k in block:
            weeks.remove(k)
        yield block
    yield weeks


def encode_week(week: int, max_week: int = 38) -> List[int]:
    a = [0 if i != week else 1 for i in range(1, max_week + 1)]
    return a


TEAMS_ID = {
    'MAL': 1,
    'GRN': 2,
    'VLL': 3,
    'LEV': 4,
    'BAR': 5,
    'ATM': 6,
    'VAL': 7,
    'ESP': 8,
    'LEG': 9,
    'GET': 10,
    'SEV': 11,
    'EIB': 12,
    'CEL': 13,
    'VIL': 14,
    'ATH': 15,
    'ALA': 16,
    'BET': 17,
    'RS0': 18,
    'OSA': 19,
    'RMA': 20
}


g_map = {
    0: [0, 0, 0, 0, 0, 0],
    1: [1, 0, 0, 0, 0, 0],
    2: [0, 1, 0, 0, 0, 0],
    3: [0, 0, 1, 0, 0, 0],
    4: [0, 0, 0, 1, 0, 0],
    5: [0, 0, 0, 0, 1, 0],
    6: [0, 0, 0, 0, 0, 1]
}


def encode_team(team: int) -> List[int]:
    t_id = TEAMS_ID.get(team)
    a = [0 if i != t_id else 1 for i in range(1, len(TEAMS_ID) + 1)]
    return a


def get_auth_class(name: str, mod):
    name = f'{name.capitalize()}Auth'
    cls = getattr(mod, name)
    return cls()

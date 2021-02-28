import json
from typing import Dict, Any, Tuple, Optional, Union, List


def encode_json(data: Dict) -> str:
    return json.dumps(data)


def decode_json(data: Any) -> Union[Dict, List, None]:
    if isinstance(data, str):
        try:
            return json.loads(data)
        except ValueError:
            return None
    return None


def post_success(data: dict):
    return {'success': True, 'errors': {}, 'data': data}


def post_error(errors: dict):
    return {'success': False, 'errors': errors, 'data': {}}


def parse_wss_payload(body: dict):
    cmd = body.get('cmd', None)
    client_id = body.get('clientId', None)
    data = body.get('body', None)
    if isinstance(cmd, str) and isinstance(client_id, str) and isinstance(data, dict):
        return cmd, client_id, data
    # TODO: DROP ALL MESSAGES WITH INVALID FORMAT BUT CAN LOG
    return None, None, None


def parse_cmd_key(name: str):
    a = name.split('_')
    return '_'.join(a[:-1]), a[-1]

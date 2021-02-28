from typing import Any, Dict, List, Optional


class ProviderSettings:
    auth: Dict
    playlists: Dict[int, Dict]
    odd_settings_id: int
    taxes_settings: Dict
    game_settings: Dict
    ext_data: Optional[Any]
    currency: Dict
    tags_id: Optional[Any]
    configured: bool

    def __init__(self):
        self.auth = {}
        self.odd_settings_id = 0
        self.playlists = {}
        self.taxes_settings = {}
        self.game_settings = {}
        self.ext_data = None
        self.tags_id = None
        self.currency = {}
        self.configured: bool = False

    @property
    def auth_staff(self) -> Dict:
        return self.auth.get('staff')

    @property
    def auth_unit(self) -> Dict:
        return self.auth.get('unit')

    @property
    def unit_id(self):
        return self.auth_staff.get('id')

    @property
    def taxes_settings_id(self):
        return self.taxes_settings.get('taxesSettingsId')

    def process_taxes_settings(self, taxes_settings_id):
        self.taxes_settings = taxes_settings_id

    def process_displays(self, displays: List):
        self.playlists = {}
        for display in displays:
            content = display.get('content')  # type: Dict
            content.pop('classType')
            playlist_id = content.pop('playlistId')
            self.playlists[playlist_id] = content

    def process_game_settings(self, game_settings):
        for game_setting in game_settings:
            game_type = game_setting.get('gameType')
            val = game_type.get('val')
            limits = game_setting.get('limits')[0]
            currency = limits.get('currencyCode')
            max_stake = limits.get('maxStake')
            min_stake = limits.get('minStake')
            max_payout = limits.get('maxPayout')
            self.game_settings[val] = {
                'currency': currency,
                'min_stake': min_stake,
                'max_stake': max_stake,
                'max_payout': max_payout
            }

    def process_localization(self, localization: Dict):
        self.currency = localization.get('currencySett').get('currency')

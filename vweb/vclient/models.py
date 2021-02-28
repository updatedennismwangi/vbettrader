"""
Custom user model
"""

import secrets

import jwt
from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .manager import UserManager


def get_default_login_data():
    return {}


def get_default_providers():
    return [
        ('betika', 'Betika'),
        ('mozzart', 'Mozzart')
    ]


def get_default_session_status():
    return [
        ('running', 'Running'),
        ('paused', 'Paused'),
        ('stopped', 'Stopped')
    ]


def get_default_providers_config():
    return {
        14036: {
            'enabled': True,
            'players': {
                'neymar': {
                    'account': 'FixedStakeAccount',
                    'max_stake': 10000,
                    'options': {}
                }
            }
        }
    }


def get_default_providers_players():
    return {
        'messi': {
            'competitions': {
                14035: {},
                14036: {}
            }
        }
    }


def get_default_provider_settings():
    return {
        'max_stake': 10000,
    }


def get_default_session_data():
    return {

    }


def get_default_ticket_data():
    return {

    }


def get_default_provider_competitions():
    games = {
        14035: {
            'name': 'Italy'
        },
        14036: {
            'name': 'Laliga'
        },
        14045: {
            'name': 'EPL Betika'
        },
        14050: {
            'name': 'KPL Premier'
        },
        41047: {
            'name': 'Bundesliga'
        }
    }
    return games


def get_default_won_data():
    return {}


class User(AbstractBaseUser, PermissionsMixin):
    """[summary]

    Arguments:
        AbstractBaseUser {[type]} -- [description]
        PermissionsMixin {[type]} -- [description]

    Returns:
        [type] -- [description]
    """

    email = models.EmailField(_('email address'), blank=False, unique=True)
    is_staff = models.BooleanField(
        _('staff status'),
        default=False,
        help_text=_('Designates whether the user can log into this admin site.'),
    )
    is_active = models.BooleanField(
        _('active'),
        default=True,
        help_text=_(
            'Designates whether this user should be treated as active. '
            'Unselect this instead of deleting accounts.'
        ),
    )
    activated = models.BooleanField(
        _('activated'),
        default=False
    )

    date_joined = models.DateTimeField(_('date joined'), default=timezone.now)

    objects = UserManager()

    EMAIL_FIELD = 'email'
    USERNAME_FIELD = 'email'

    # REQUIRED_FIELDS = ['email']

    def __repr__(self):
        """
        Returns a string representation of this `User`.

        This string is used when a `User` is printed in the console.
        """
        return self.email

    def __str__(self):
        return self.email

    @property
    def new_token(self):
        return secrets.token_hex(16)

    def get_full_name(self):
        """
        This method is required by Django for things like handling emails.
        Typically this would be the user's first and last name. Since we do
        not store the user's real name, we return their username instead.
        """
        return self.email

    def jwt_token(self, token):
        return self._generate_jwt_token(token)

    def get_short_name(self):
        """
        This method is required by Django for things like handling emails.
        Typically, this would be the user's first name. Since we do not store
        the user's real name, we return their username instead.
        """
        return self.email

    def _generate_jwt_token(self, token: str):
        """
        Generates a JSON Web Token that stores this user's ID and access token
        """
        return jwt.encode({
            'id': self.pk,
            'token': token,
        }, settings.SECRET_KEY, algorithm='HS256')

    class Meta:
        app_label = 'vclient'


class Token(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="auth_token", verbose_name=_("User"))
    token = models.CharField(_("Token"), max_length=32, db_index=True, unique=True)
    created = models.DateTimeField(_('Created'), auto_now_add=True)
    objects = models.Manager()

    class Meta:
        db_table = 'Token'
        app_label = 'vclient'

    def __repr__(self):
        return self.token


class Providers(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="providers",
                             verbose_name=_("Providers"))
    username = models.CharField(_("Username"), max_length=70, db_index=True)
    provider = models.CharField(_("Provider"), max_length=10, choices=get_default_providers())
    token = models.JSONField(_("Token"), default=get_default_login_data)
    enabled = models.BooleanField(_("Enabled"), default=True)
    objects = models.Manager()

    class Meta:
        db_table = 'Providers'
        app_label = 'vclient'


class ProviderConfig(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="provider_config",
                             verbose_name=_("ProvidersConfig"))
    provider = models.ForeignKey(Providers, related_name="config", on_delete=models.CASCADE,
                                 verbose_name=_("Provider"), default=1)
    competitions = models.JSONField(_('Competition'), default=get_default_providers_config)
    players = models.JSONField(_('Players'), default=get_default_providers_players)
    objects = models.Manager()

    class Meta:
        app_label = "vclient"


class ProviderInstalled(models.Model):
    name = models.CharField(_("Name"), max_length=10, choices=get_default_providers())
    competitions = models.JSONField(_("Competitions"), default=get_default_provider_competitions)
    objects = models.Manager()

    class Meta:
        app_label = "vclient"


class Sessions(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions",
                             verbose_name="User")
    provider = models.ForeignKey(Providers, related_name="sessions", on_delete=models.CASCADE,
                                 verbose_name=_("Provider"))
    session_id = models.IntegerField(_("session_id"), db_index=True)
    status = models.CharField(_("status"), max_length=10)
    data = models.JSONField(_('data'), default=get_default_session_data)
    objects = models.Manager()

    class Meta:
        app_label = "vclient"


class LiveSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="live_sessions",
                             verbose_name="User")
    provider = models.ForeignKey(Providers, related_name="live_sessions", on_delete=models.CASCADE,
                                 verbose_name=_("Provider"))
    session_id = models.AutoField(_("Session Id"), primary_key=True)

    status = models.CharField(_("Status"), max_length=10, choices=get_default_session_status())

    competitions = models.JSONField(_("Competitions"))

    data = models.JSONField(_("Data"))

    objects = models.Manager()

    class Meta:
        app_label = "vclient"


class Tickets(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="tickets",
                             verbose_name="Tickets")
    provider = models.ForeignKey(Providers, related_name="tickets", on_delete=models.CASCADE,
                                 verbose_name="Provider")
    live_session = models.ForeignKey(LiveSession, related_name="tickets", on_delete=models.CASCADE,
                                     verbose_name="Live Session", blank=True)
    ticket_key = models.AutoField(_("Ticket Key"), primary_key=True)
    time_created = models.DateTimeField(auto_now_add=True)
    demo = models.BooleanField(_("Demo"), default=True)
    resolved = models.BooleanField(_("Resolved"), default=False)
    ticket_id = models.IntegerField(_("Ticket Id"), db_index=True, default=-1)
    time_paid = models.CharField(_("Time Paid"), default='', max_length=32)
    time_send = models.CharField(_("Time Send"), default='', max_length=32)
    time_register = models.CharField(_("Time Register"), default='', max_length=32)
    time_resolved = models.CharField(_("Time Resolved"), default='', max_length=32)
    ticket_status = models.CharField(_("Ticket Status"), default='', max_length=20)
    status = models.CharField(_('Status'), default='READY', max_length=20)
    details = models.JSONField(_("Details"), default=get_default_ticket_data)
    won_data = models.JSONField(_("Won Data"), default=get_default_won_data)
    payment_data = models.JSONField(_("Payment Data"), default=get_default_won_data)
    server_hash = models.CharField(_("Server Hash"), default='', max_length=10)
    ip = models.CharField(_("Ip"), default='', max_length=15)
    objects = models.Manager()

    class Meta:
        app_label = "vclient"


class Pins(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="pins", verbose_name=_("Pins"))
    pin = models.IntegerField(_("Pin"))
    objects = models.Manager()

    class Meta:
        app_label = "vclient"


class ForgotTokens(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="forgot_tokens",
                             verbose_name=_("Forgot Tokens"))
    is_used = models.BooleanField(default=False)
    token = models.CharField(max_length=48)
    date = models.DateTimeField(auto_now=True)

    objects = models.Manager()

    class Meta:
        app_label = "vclient"


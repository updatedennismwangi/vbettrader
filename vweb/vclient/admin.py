from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from vweb.vclient.models import Token, User, Providers, ProviderConfig, ProviderInstalled, Tickets, LiveSession


class CustomUserAdmin(UserAdmin):
    # add_form = CustomUserCreationForm
    # form = CustomUserChangeForm
    model = User
    list_display = ['email']
    ordering = ('email',)


admin.site.register(User, CustomUserAdmin)
admin.site.register(Token)
admin.site.register(Providers)
admin.site.register(ProviderConfig)
admin.site.register(ProviderInstalled)
admin.site.register(Tickets)
admin.site.register(LiveSession)
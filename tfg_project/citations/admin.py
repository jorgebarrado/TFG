"""Configuración del panel de administración para la app citations."""

from django.contrib import admin

from .models import Conversation, IncorrectCitation, Message, UserProfile

admin.site.register(IncorrectCitation)
admin.site.register(UserProfile)
admin.site.register(Conversation)
admin.site.register(Message)

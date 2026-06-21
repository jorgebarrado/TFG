# Registro de modelos en el panel de administración de Django.
from django.contrib import admin

from .models import Conversation, IncorrectCitation, Message, UserProfile

admin.site.register(IncorrectCitation)
admin.site.register(UserProfile)
admin.site.register(Conversation)
admin.site.register(Message)

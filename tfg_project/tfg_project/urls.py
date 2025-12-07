from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from citations.views import message_views, user_views
from citations.views.page_views import home

urlpatterns = [
    path("accounts/", include("allauth.urls")),
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    path("citations/", include("citations.urls")),
    path("messages/", message_views.inbox, name="messages_inbox"),
    path(
        "messages/new/<str:username>/",
        message_views.new_conversation,
        name="new_conversation",
    ),
    path(
        "messages/<int:conversation_id>/",
        message_views.conversation_detail,
        name="conversation_detail",
    ),
    path("perfil/<str:username>/", user_views.profile_view, name="profile"),
]

urlpatterns += [
    path("i18n/", include("django.conf.urls.i18n")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

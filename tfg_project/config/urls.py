# Enrutador raíz: conecta todas las URLs del proyecto con las vistas de citations y el panel de administración.
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from citations.views import message_views, notification_views, user_views
from citations.views.page_views import home

urlpatterns = [
    path("accounts/", include("allauth.urls")),
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    path(
        "notifications/",
        notification_views.notification_list,
        name="notifications_list",
    ),
    path(
        "notifications/mark-all-read/",
        notification_views.mark_all_read,
        name="notifications_mark_all_read",
    ),
    path(
        "notifications/<int:pk>/read/",
        notification_views.notification_read,
        name="notifications_read",
    ),
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

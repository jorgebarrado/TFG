from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from citations.views.page_views import home

urlpatterns = [
    path("accounts/", include("allauth.urls")),
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    path("citations/", include("citations.urls")),
]

urlpatterns += [
    path("i18n/", include("django.conf.urls.i18n")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

from django.contrib import admin
from django.urls import include, path

from citations.views import home

urlpatterns = [
    path("accounts/", include("allauth.urls")),
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    path("citations/", include("citations.urls")),
]

urlpatterns += [
    path("i18n/", include("django.conf.urls.i18n")),
]

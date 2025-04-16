from django.contrib import admin
from django.urls import path, include
from citations.views import home
from django.conf.urls.i18n import i18n_patterns
from citations import views

urlpatterns = [
    path('', home, name='home'),  # Página de inicio
    path('admin/', admin.site.urls),
    path('citations/', include('citations.urls')),  # Todas las rutas de tu app
]

urlpatterns += [
    path('i18n/', include('django.conf.urls.i18n')),
]
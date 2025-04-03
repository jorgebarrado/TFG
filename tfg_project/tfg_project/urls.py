from django.contrib import admin
from django.urls import path, include
from citations.views import home

urlpatterns = [
    path('', home, name='home'),  # Página de inicio
    path('admin/', admin.site.urls),
    path('citations/', include('citations.urls')),  # Todas las rutas de tu app
]

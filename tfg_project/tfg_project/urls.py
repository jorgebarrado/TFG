from django.contrib import admin
from django.urls import path, include
from citations.views import home, register_user, login_user
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('', home, name='home'),
    path('admin/', admin.site.urls),
    path('register/', register_user, name='register'),
    path('login/', login_user, name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='home'), name='logout'),
    path('citations/', include('citations.urls')),
]
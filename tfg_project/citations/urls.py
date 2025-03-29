from django.urls import path
from . import views
from .views import get_all_metadata_from_doi

urlpatterns = [
    path('submit/', views.submit_incorrect_citation, name='submit_incorrect_citation'), # url para crear el registro
    path('submitted/', views.citation_submitted, name='citation_submitted'), # url despues de enciar el registro
]


urlpatterns += [
    path('get_all_metadata/', get_all_metadata_from_doi, name='get_all_metadata'),
]

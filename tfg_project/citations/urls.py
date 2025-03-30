from django.urls import path
from .views import (
    ajax_submit_citation,
    submit_incorrect_citation,
    citation_list,
    citation_submitted,
    get_all_metadata_from_doi
)

urlpatterns = [
    path('submit/', submit_incorrect_citation, name='submit_incorrect_citation'),
    path('list/', citation_list, name='citation_list'),
    path('submitted/', citation_submitted, name='citation_submitted'),
    path('get_all_metadata/', get_all_metadata_from_doi, name='get_all_metadata'),
    path('ajax_submit/', ajax_submit_citation, name='ajax_submit'),
]

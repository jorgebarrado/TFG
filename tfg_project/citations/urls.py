from django.urls import path
from . import views
from .views import (
    ajax_submit_citation,
    submit_incorrect_citation,
    citation_list,
    citation_submitted,
    get_all_metadata_from_doi,
    citation_detail,
    login_view,
    register_view,
    logout_view,
    delete_comment,
)

urlpatterns = [
    path('perfil/semantic-citations/', views.semantic_citations_view, name='semantic_citations'),
    path('perfil/dblp-articulos/', views.dblp_articles_view, name='dblp_articles'),
    path('submit/', submit_incorrect_citation, name='submit_incorrect_citation'),
    path('list/', citation_list, name='citation_list'),
    path('submitted/', citation_submitted, name='citation_submitted'),
    path('get_all_metadata/', get_all_metadata_from_doi, name='get_all_metadata'),
    path('ajax_submit/', ajax_submit_citation, name='ajax_submit'),
    path('report/<int:pk>/', citation_detail, name='citation_detail'),
    path('login/', login_view, name='login'),
    path('register/', register_view, name='register'),
    path('logout/', logout_view, name='logout'),
    path('comments/delete/<int:pk>/', delete_comment, name='delete_comment'),
    path('citations/toggle_saved/', views.toggle_saved, name='toggle_saved'),
    path('perfil/mis-reportes/', views.my_reports, name='my_reports'),
    path('perfil/mis-comentarios/', views.my_comments, name='my_comments'),
    path('perfil/guardados/', views.my_saved, name='my_saved'),
    path('perfil/ajustes/', views.account_settings, name='account_settings'),
    path('vote/', views.vote_view, name='vote'),
    path("ajax/register/", views.register_ajax, name="register_ajax"),
    path("search_suggest/", views.citation_suggest, name="citation_suggest"),
    path("api/doi/", views.fetch_doi_metadata, name="fetch_doi"),
]



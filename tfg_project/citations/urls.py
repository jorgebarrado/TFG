# citations/urls.py
from django.urls import path
from . import views_ai, views_api, views_reports
from .views import ajax_views, auth_views, page_views, user_views

urlpatterns = [
    # Page Views
    path(
        "perfil/semantic-citations/",
        page_views.semantic_citations_view,
        name="semantic_citations",
    ),
    path("list/", page_views.citation_list, name="citation_list"),
    path("report/<int:pk>/", page_views.citation_detail, name="citation_detail"),
    path(
        "report/wizard/",
        views_reports.create_report_wizard,
        name="create_report_wizard",
    ),
    path(
        "reports/create/ajax/",
        views_reports.ajax_submit_report,
        name="ajax_submit_report",
    ),
    path(
        "reports/<int:pk>/ai-detect/",
        views_ai.citation_ai_detect,
        name="citation_ai_detect",
    ),
    path(
        "reports/<int:pk>/ai-evaluate/",
        views_ai.citation_ai_evaluate,
        name="citation_ai_evaluate",
    ),
    # User Views
    path(
        "perfil/dblp-articulos/",
        user_views.dblp_articles_view,
        name="dblp_articles",
    ),
    path("perfil/mis-reportes/", user_views.my_reports, name="my_reports"),
    path("perfil/mis-comentarios/", user_views.my_comments, name="my_comments"),
    path("perfil/guardados/", user_views.my_saved, name="my_saved"),
    path("perfil/", user_views.my_profile, name="my_profile"),
    path("perfil/ajustes/", user_views.account_settings, name="account_settings"),
    # AJAX Views
    path(
        "get_all_metadata/",
        ajax_views.get_all_metadata_from_doi,
        name="get_all_metadata",
    ),
    path("ajax_submit/", ajax_views.ajax_submit_citation, name="ajax_submit"),
    path("comments/delete/<int:pk>/", ajax_views.delete_comment, name="delete_comment"),
    path("citations/toggle_saved/", ajax_views.toggle_saved, name="toggle_saved"),
    path("vote/", ajax_views.vote_view, name="vote"),
    path("ajax/register/", ajax_views.register_ajax, name="register_ajax"),
    path("search_suggest/", ajax_views.citation_suggest, name="citation_suggest"),
    path("api/doi/", ajax_views.fetch_doi_metadata, name="fetch_doi"),
    # Authentication
    path("login/", auth_views.login_view, name="login"),
    path("register/", auth_views.register_view, name="register"),
    path("logout/", auth_views.logout_view, name="logout"),
    # APIs nuevas/ajustadas
    path(
        "api/extract-citations/",
        views_api.api_extract_citations,
        name="api_extract_citations",
    ),
    path(
        "api/get-citation-context/",
        views_api.get_citation_context,
        name="get_citation_context",
    ),
    path(
        "api/pdf-contexts/",
        views_api.api_pdf_citation_contexts,
        name="api_pdf_citation_contexts",
    ),
    path(
        "api/pdf-contexts-upload/",
        views_api.api_pdf_citation_contexts_upload,
        name="api_pdf_citation_contexts_upload",
    ),
    path(
        "api/get-semantic-citations/",
        ajax_views.get_semantic_citations,
        name="get_semantic_citations",
    ),
    path(
        "api/semantic-citation-analysis/",
        views_api.api_semantic_citation_analysis,
        name="api_semantic_citation_analysis",
    ),
    path("report/<int:pk>/preview/", page_views.citation_preview, name="citation_preview"),
]

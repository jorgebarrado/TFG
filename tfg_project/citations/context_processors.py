from .forms import LoginForm, RegisterForm
from .models import IncorrectCitation, Notification


def login_register_forms(request):
    return {
        "login_form": LoginForm(),
        "register_form": RegisterForm(),
    }


def notifications_context(request):
    if not request.user.is_authenticated:
        return {
            "notifications_unread_count": 0,
            "notifications_latest": [],
        }

    latest = (
        Notification.objects.filter(user=request.user)
        .only("id", "title", "message", "url", "is_read", "created_at")
        .order_by("-created_at")[:5]
    )
    unread_count = Notification.objects.filter(
        user=request.user,
        is_read=False,
    ).count()

    return {
        "notifications_unread_count": unread_count,
        "notifications_latest": latest,
    }


def next_report_number_context(request):
    try:
        latest_id = (
            IncorrectCitation.objects.order_by("-id")
            .values_list("id", flat=True)
            .first()
            or 0
        )
        next_report_number = int(latest_id) + 1
    except Exception:  # pylint: disable=broad-except
        next_report_number = 1

    return {
        "next_report_number": next_report_number,
    }

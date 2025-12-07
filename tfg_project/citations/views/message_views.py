"""Views for simple user-to-user messaging."""

from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render

from ..forms import MessageForm
from ..models import Conversation, Message

User = get_user_model()


def _other_participants(conversation, current_user):
    return [
        participant
        for participant in conversation.participants.all()
        if participant != current_user
    ]


@login_required
def inbox(request):
    messages_prefetch = Prefetch(
        "messages",
        queryset=Message.objects.select_related("sender").order_by("created_at"),
    )

    conversations = (
        Conversation.objects.filter(participants=request.user)
        .prefetch_related("participants", messages_prefetch)
        .annotate(
            latest_message_at=Max("messages__created_at"),
            unread_count=Count(
                "messages",
                filter=Q(messages__is_read=False)
                & ~Q(messages__sender=request.user),
            ),
        )
        .order_by("-latest_message_at", "-created_at")
    )

    for conversation in conversations:
        conversation.other_participants = _other_participants(
            conversation, request.user
        )

    context = {"conversations": conversations}
    return render(request, "messages/inbox.html", context)


@login_required
def conversation_detail(request, conversation_id):
    conversation = get_object_or_404(
        Conversation.objects.filter(participants=request.user).prefetch_related(
            "participants"
        ),
        pk=conversation_id,
    )

    conversation.other_participants = _other_participants(
        conversation, request.user
    )

    messages = conversation.messages.select_related("sender").order_by("created_at")

    if request.method == "POST":
        form = MessageForm(request.POST)
        if form.is_valid():
            Message.objects.create(
                conversation=conversation,
                sender=request.user,
                content=form.cleaned_data["content"],
            )
            return redirect("conversation_detail", conversation_id=conversation.id)
    else:
        form = MessageForm()

    conversation.messages.filter(is_read=False).exclude(
        sender=request.user
    ).update(is_read=True)

    context = {"conversation": conversation, "form": form, "messages": messages}
    return render(request, "messages/conversation.html", context)


@login_required
def new_conversation(request, username):
    other_user = get_object_or_404(User, username=username)

    base_qs = Conversation.objects.filter(participants=request.user).filter(
        participants=other_user
    )

    expected_participants = 1 if other_user == request.user else 2
    conversation = (
        base_qs.annotate(num_participants=Count("participants"))
        .filter(num_participants=expected_participants)
        .first()
    )

    if conversation is None:
        conversation = Conversation.objects.create()
        conversation.participants.add(request.user, other_user)

    return redirect("conversation_detail", conversation_id=conversation.id)

"""Vistas para el sistema de mensajería simple entre usuarios."""

from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render

from ..forms import MessageForm
from ..models import Conversation, Message

User = get_user_model()


def _other_participants(conversation, current_user):
    """Devuelve los participantes de una conversación excluyendo al usuario actual.

    Args:
        conversation (Conversation): La conversación.
        current_user (User): El usuario actual.

    Returns:
        List[User]: Lista de otros participantes.
    """
    return [
        participant
        for participant in conversation.participants.all()
        if participant != current_user
    ]


@login_required
def inbox(request):
    """Muestra la bandeja de entrada del usuario.

    Lista las conversaciones ordenadas por el mensaje más reciente,
    mostrando contadores de mensajes no leídos.

    Args:
        request: Objeto HttpRequest.

    Returns:
        HttpResponse: Renderiza 'messages/inbox.html'.
    """
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
    """Muestra el detalle de una conversación y permite enviar nuevos mensajes.

    Marca como leídos los mensajes recibidos al abrir la conversación.

    Args:
        request: Objeto HttpRequest.
        conversation_id (int): ID de la conversación.

    Returns:
        HttpResponse: Renderiza 'messages/conversation.html'.
    """
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
    """Inicia o recupera una conversación privada con otro usuario.

    Si ya existe una conversación entre ambos (y solo ellos), redirige a ella.
    Si no, crea una nueva.

    Args:
        request: Objeto HttpRequest.
        username (str): Nombre de usuario del destinatario.

    Returns:
        HttpResponse: Redirección a la vista de detalle de la conversación.
    """
    other_user = get_object_or_404(User, username=username)

    # 1. Obtener todas las conversaciones donde participan AMBOS
    existing_conversations = Conversation.objects.filter(
        participants=request.user
    ).filter(
        participants=other_user
    )

    found_conversation = None

    # 2. Verificar cuál de ellas es EXCLUSIVAMENTE entre estos dos (sin terceros)
    expected_count = 1 if other_user == request.user else 2

    for conversation in existing_conversations:
        if conversation.participants.count() == expected_count:
            found_conversation = conversation
            break

    # 3. Redirigir o crear
    if found_conversation:
        return redirect("conversation_detail", conversation_id=found_conversation.id)

    conversation = Conversation.objects.create()
    conversation.participants.add(request.user, other_user)
    return redirect("conversation_detail", conversation_id=conversation.id)

"""AI Data Analyst: conversations and grounded questions."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.analyst import analyse
from ..ai.providers import ai_status
from ..config import get_settings
from ..db import get_db, utcnow
from ..deps import WorkspaceContext, client_ip, editor_context, enforce_rate_limit, get_ready_dataset, get_version, version_schema, workspace_context
from ..models import AIConversation, AIMessage, DataProfile, Dataset
from ..services import storage
from ..services.activity import audit, record_analysis

router = APIRouter(prefix="/analyst", tags=["AI Data Analyst"])


class AskRequest(BaseModel):
    dataset_id: str
    question: str = Field(min_length=2, max_length=1000)
    conversation_id: str | None = None


def _message_payload(message: AIMessage) -> dict:
    return {"id": message.id, "role": message.role, "content": message.content, "response": message.response, "mode": message.mode, "provider": message.provider, "model": message.model, "created_at": message.created_at}


def _conversation(db: Session, ctx: WorkspaceContext, conversation_id: str) -> AIConversation:
    conversation = db.scalar(select(AIConversation).where(AIConversation.id == conversation_id, AIConversation.workspace_id == ctx.id, AIConversation.user_id == ctx.user.id))
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conversation


@router.get("/status")
def status(_ctx: WorkspaceContext = Depends(workspace_context)):
    return ai_status()


@router.get("/conversations")
def list_conversations(dataset_id: str | None = None, ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    query = select(AIConversation, Dataset.name).join(Dataset, Dataset.id == AIConversation.dataset_id).where(AIConversation.workspace_id == ctx.id, AIConversation.user_id == ctx.user.id)
    if dataset_id:
        query = query.where(AIConversation.dataset_id == dataset_id)
    rows = db.execute(query.order_by(AIConversation.updated_at.desc()).limit(100)).all()
    return [{"id": c.id, "title": c.title, "dataset_id": c.dataset_id, "dataset_name": name, "updated_at": c.updated_at} for c, name in rows]


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    conversation = _conversation(db, ctx, conversation_id)
    messages = db.scalars(select(AIMessage).where(AIMessage.conversation_id == conversation.id).order_by(AIMessage.created_at, AIMessage.role.desc())).all()
    return {"id": conversation.id, "title": conversation.title, "dataset_id": conversation.dataset_id, "messages": [_message_payload(m) for m in messages]}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    db.delete(_conversation(db, ctx, conversation_id))
    db.commit()
    return {"ok": True}


@router.post("/ask")
def ask(body: AskRequest, request: Request, ctx: WorkspaceContext = Depends(editor_context), db: Session = Depends(get_db)):
    enforce_rate_limit(request, "ai", get_settings().rate_limit_ai_per_minute)
    dataset = get_ready_dataset(db, ctx, body.dataset_id)
    version = get_version(db, dataset)
    schema = version_schema(db, version)
    stored = db.scalar(select(DataProfile).where(DataProfile.version_id == version.id))
    question = " ".join(body.question.split())

    if body.conversation_id:
        conversation = _conversation(db, ctx, body.conversation_id)
        if conversation.dataset_id != dataset.id:
            raise HTTPException(status_code=409, detail="This conversation belongs to a different dataset. Start a new conversation.")
    else:
        conversation = AIConversation(workspace_id=ctx.id, dataset_id=dataset.id, user_id=ctx.user.id, title=question[:120])
        db.add(conversation)
        db.flush()

    earlier = db.scalars(select(AIMessage).where(AIMessage.conversation_id == conversation.id).order_by(AIMessage.created_at.desc()).limit(12)).all()
    history = [{"role": m.role, "text": (m.response or {}).get("direct_answer") if m.role == "assistant" else m.content} for m in reversed(earlier)]

    response = analyse(question, dataset_name=dataset.name, version_number=version.version_number, schema=schema, path=storage.resolve_ref(version.storage_ref), profile=stored.profile, quality=stored.quality, history=history)

    db.add(AIMessage(conversation_id=conversation.id, role="user", content=question))
    assistant = AIMessage(conversation_id=conversation.id, role="assistant", content=response["direct_answer"], response=response, mode=response["mode"], provider=response["provider"], model=response["model"], usage=response["usage"])
    db.add(assistant)
    conversation.updated_at = utcnow()
    dataset.last_analysed_at = utcnow()
    record_analysis(db, workspace_id=ctx.id, dataset_id=dataset.id, user_id=ctx.user.id, name=question, analysis_type="ai_question", link=f"/analyst?conversation={conversation.id}",
                    status="completed" if response["status"] == "answered" else "unsupported", summary={"mode": response["mode"]})
    # The question text is not logged here, because it may name sensitive values.
    audit(db, "ai.question", workspace_id=ctx.id, user_id=ctx.user.id, entity_type="dataset", entity_id=dataset.id, detail={"mode": response["mode"], "provider": response["provider"], "usage": response["usage"]}, ip=client_ip(request))
    db.commit()
    return {"conversation_id": conversation.id, "message": _message_payload(assistant)}

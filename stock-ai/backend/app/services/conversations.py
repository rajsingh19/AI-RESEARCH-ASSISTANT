from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List
from sqlalchemy.orm import Session
import uuid
import models
from deps import get_db, get_current_user
from datetime import datetime,timezone

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

class ConversationCreate(BaseModel):
    title: str = "New Chat"

class MessageCreate(BaseModel):
    role: str
    content: str

@router.get("")
def get_conversations(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    # Returns ONLY the authenticated user's chats
    return db.query(models.Conversation).filter(models.Conversation.user_id == current_user.id).order_by(models.Conversation.updated_at.desc()).all()

@router.post("")
def create_conversation(conv_data: ConversationCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    conv_id = f"conv_{uuid.uuid4().hex[:12]}"
    new_conv = models.Conversation(id=conv_id, user_id=current_user.id, title=conv_data.title)
    db.add(new_conv)
    db.commit()
    db.refresh(new_conv)
    return new_conv

@router.get("/{id}")
def get_conversation_details(id: str, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    conv = db.query(models.Conversation).filter(models.Conversation.id == id, models.Conversation.user_id == current_user.id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found or access denied")
    
    messages = db.query(models.Message).filter(models.Message.conversation_id == id).order_by(models.Message.timestamp.ascii()).all()
    return {"conversation": conv, "messages": messages}

@router.post("/{id}/messages")
def save_message(id: str, msg_data: MessageCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    conv = db.query(models.Conversation).filter(models.Conversation.id == id, models.Conversation.user_id == current_user.id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found or access denied")
    
    new_msg = models.Message(conversation_id=id, role=msg_data.role, content=msg_data.content)
    conv.updated_at = models.datetime.now(models.timezone.utc) # Update parent timestamp
    db.add(new_msg)
    db.commit()
    db.refresh(new_msg)
    return new_msg

@router.delete("/{id}")
def delete_conversation(id: str, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    conv = db.query(models.Conversation).filter(models.Conversation.id == id, models.Conversation.user_id == current_user.id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.delete(conv)
    db.commit()
    return {"detail": "Conversation deleted"}
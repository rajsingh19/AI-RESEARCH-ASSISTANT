import sys
from pathlib import Path
import uuid

# Add backend directory to path
backend_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_dir))

from app.database.database import SessionLocal, Base, engine
from app.models.conversation import Conversation, Message
from app.services.ai_service import get_ai_service
from app.api.chat import generate_chat_title


def test_chat_history():
    print("Initializing test database...")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # Create a conversation
    conv_id = f"test_{uuid.uuid4().hex[:8]}"
    print(f"Creating conversation: {conv_id}")
    conv = Conversation(id=conv_id, title="New Chat")
    db.add(conv)
    db.commit()

    # Verify creation
    fetched = db.query(Conversation).filter(Conversation.id == conv_id).first()
    assert fetched is not None, "Failed to retrieve conversation"
    assert fetched.title == "New Chat", "Failed title match"

    # Test title generation via AI
    ai = get_ai_service()
    first_query = "Revenue growth of TCS over last 5 years"
    print("Testing AI title generation...")
    ai_title = generate_chat_title(first_query, ai)
    print(f"Generated Title: {ai_title}")
    assert len(ai_title) > 0, "Title cannot be empty"

    # Add messages
    print("Adding user message...")
    user_msg = Message(
        conversation_id=conv_id,
        role="user",
        content=first_query
    )
    db.add(user_msg)
    db.commit()

    print("Adding assistant response...")
    assistant_msg = Message(
        conversation_id=conv_id,
        role="assistant",
        content="Here are TCS results...",
        intent="company_metric",
        companies="[\"TCS\"]",
        metrics="[\"revenue\"]",
        financial_data="{}",
        documents="[]",
        news="[]",
        sources="[]",
        warnings="[]"
    )
    db.add(assistant_msg)
    db.commit()

    # Verify retrieval
    db.refresh(conv)
    print(f"Messages count: {len(conv.messages)}")
    assert len(conv.messages) == 2, "Message count must be exactly 2"
    assert conv.messages[0].role == "user"
    assert conv.messages[1].role == "assistant"

    # Clean up test conversation
    print("Cleaning up test conversation...")
    db.delete(conv)
    db.commit()
    
    # Check messages cascade deleted
    msg_count = db.query(Message).filter(Message.conversation_id == conv_id).count()
    assert msg_count == 0, "Message cascade delete failed"

    print("\n=========================================")
    print("  CONVERSATION HISTORY API DB STATUS: OK")
    print("=========================================\n")


if __name__ == "__main__":
    test_chat_history()

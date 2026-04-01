import os
import json
import uuid
import openai
import asyncio
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form, Response
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from dotenv import load_dotenv

from prompts import (
    MASTER_TEACHER_PROMPT, 
    CONCEPT_EXPLAINER_PROMPT,
    CASE_LAW_SUMMARY_PROMPT,
    ANSWER_GENERATOR_PROMPT,
    QUIZ_GENERATOR_PROMPT,
    ANSWER_EVALUATOR_PROMPT,
    STUDY_PLANNER_PROMPT,
    SYLLABUS_SMART_PROMPT
)
from document_service import get_text_from_file
from video_service import extract_video_id, get_youtube_transcript, transcribe_video_file
from pdf_service import generate_judicial_pdf
from file_service import save_content_locally
from database import init_db, save_document, get_document
from auth import (
    User, create_user, get_user_by_email,
    verify_password, create_access_token, get_current_user
)
from fastapi.responses import StreamingResponse, Response

load_dotenv()

app = FastAPI(title="Legaify API", description="AI Tutor for KSLU Law Students")

@app.on_event("startup")
def on_startup():
    """Initialize SQLite database tables on server start."""
    init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# Global client variable (initialized lazily)
_client = None

def get_ai_client():
    """Lazily initialize the OpenAI client."""
    global _client
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or api_key == "your_openai_api_key_here":
        raise HTTPException(
            status_code=500, 
            detail="OpenAI API Key is missing. Please add it to your .env file to use AI features."
        )
    
    if _client is None:
        _client = openai.OpenAI(api_key=api_key)
    return _client

# ── Models ────────────────────────────────────────────────────────────────────

class TopicRequest(BaseModel):
    program: str
    semester: str
    subject: str
    unit: str
    topic: str
    language: Optional[str] = "en"

class CaseRequest(BaseModel):
    case_name: str

class EvaluationRequest(BaseModel):
    question: str
    student_answer: str

class PlannerRequest(BaseModel):
    program: str
    subject: str
    topic_count: str
    exam_date: str

class VideoRequest(BaseModel):
    url: str

class PDFExportRequest(BaseModel):
    title: str
    content: str

class DocChatRequest(BaseModel):
    doc_id: str
    question: str

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

# ── Auth Endpoints ────────────────────────────────────────────────────────────

@app.post("/api/auth/register")
def register(req: RegisterRequest):
    """Register a new user. Returns a JWT access token."""
    if get_user_by_email(req.email):
        raise HTTPException(status_code=400, detail="An account with this email already exists.")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    user = create_user(name=req.name, email=req.email, password=req.password)
    token = create_access_token(user.id, user.email, user.name)
    return {"access_token": token, "token_type": "bearer", "name": user.name, "email": user.email}

@app.post("/api/auth/login")
def login(req: LoginRequest):
    """Login with email and password. Returns a JWT access token."""
    user = get_user_by_email(req.email)
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    token = create_access_token(user.id, user.email, user.name)
    return {"access_token": token, "token_type": "bearer", "name": user.name, "email": user.email}

@app.get("/api/auth/me")
def get_me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user's info."""
    return {"id": current_user.id, "name": current_user.name, "email": current_user.email}

# ── Syllabus Endpoint ─────────────────────────────────────────────────────────

@app.get("/api/tutor/syllabus")
async def get_syllabus():
    """Fetch the full KSLU syllabus from disk."""
    try:
        with open("kslu_syllabus.json", "r") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Core AI Endpoints ───────────────────────────────────────────────────────────

@app.post("/api/tutor/explain")
async def explain_topic(req: TopicRequest):
    """Explain a topic using the Master Teacher Prompt with live streaming."""
    prompt = MASTER_TEACHER_PROMPT.format(
        PROGRAM=req.program,
        SEMESTER=req.semester,
        SUBJECT=req.subject,
        UNIT=req.unit,
        TOPIC=req.topic
    )
    
    try:
        client = get_ai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            stream=True
        )
        
        def generate():
            for chunk in response:
                if len(chunk.choices) > 0 and chunk.choices[0].delta.content is not None:
                    yield chunk.choices[0].delta.content
                    
        return StreamingResponse(generate(), media_type="text/plain")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/tutor/case-summary")
async def summarize_case(req: CaseRequest):
    """Summarize a case law with live streaming."""
    prompt = CASE_LAW_SUMMARY_PROMPT.format(CASE_NAME=req.case_name)
    try:
        client = get_ai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            stream=True
        )
        
        def generate():
            for chunk in response:
                if len(chunk.choices) > 0 and chunk.choices[0].delta.content is not None:
                    yield chunk.choices[0].delta.content
                    
        return StreamingResponse(generate(), media_type="text/plain")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/tutor/evaluate")
async def evaluate_answer(req: EvaluationRequest):
    """Evaluate a student's answer using GPT-4o."""
    prompt = ANSWER_EVALUATOR_PROMPT.format(
        QUESTION=req.question,
        STUDENT_ANSWER=req.student_answer
    )
    try:
        client = get_ai_client()
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        return {"content": response.choices[0].message.content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/tutor/plan")
async def generate_plan(req: PlannerRequest):
    """Generate a study plan."""
    prompt = STUDY_PLANNER_PROMPT.format(
        PROGRAM=req.program,
        SUBJECT=req.subject,
        TOPIC_COUNT=req.topic_count,
        EXAM_DATE=req.exam_date
    )
    try:
        client = get_ai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        return {"content": response.choices[0].message.content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/tutor/quiz")
async def generate_quiz(req: TopicRequest):
    """Generate a quiz for a topic."""
    prompt = QUIZ_GENERATOR_PROMPT.format(TOPIC=req.topic)
    try:
        client = get_ai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        return {"content": response.choices[0].message.content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Document AI Endpoints ──────────────────────────────────────────────────────

@app.post("/api/docs/upload")
async def upload_document(file: UploadFile = File(...)):
    """Upload PDF/Word/Text and extract contents, persist to SQLite."""
    try:
        content = await file.read()
        text = get_text_from_file(file.filename, content)
        doc_id = save_document(filename=file.filename, text=text)
        return {"doc_id": doc_id, "filename": file.filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/docs/summarize")
async def summarize_document(doc_id: str):
    """Summarize the document context."""
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found. It may have expired (24h limit) — please re-upload.")
    
    prompt = f"Summarize the following legal document for a law student:\n\n{doc.text[:12000]}"
    try:
        client = get_ai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        return {"content": response.choices[0].message.content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/docs/chat")
async def chat_with_document(req: DocChatRequest):
    """Refined RAG-lite chat with document context."""
    doc = get_document(req.doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found. It may have expired (24h limit) — please re-upload.")
    
    prompt = f"Context:\n{doc.text[:12000]}\n\nQuestion: {req.question}"
    try:
        client = get_ai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        return {"content": response.choices[0].message.content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def stream_summary_generator(prompt: str, client):
    """Async generator to stream OpenAI response chunks."""
    try:
        # Use the sync client in a stream-ready way
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            stream=True
        )
        for chunk in response:
            if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
                await asyncio.sleep(0.01) # Small delay for smoother frontend rendering
    except Exception as e:
        yield f"\n\n[Streaming Error: {str(e)}]"

@app.post("/api/video/summarize")
async def summarize_youtube_video(req: VideoRequest):
    """Transcribe and stream summary of a YouTube video."""
    video_id = extract_video_id(req.url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    
    try:
        client = get_ai_client()
        transcript = get_youtube_transcript(video_id, client=client)
        
        prompt = f"""You are a KSLU Law Professor. Summarize the following legal lecture/video transcript into structured exam-oriented notes.
        Include:
        1. Core Legal Principles
        2. Relevant Sections/Acts mentioned
        3. Key Case Laws mentioned
        4. Exam-style summary (5-10 marks)
        
        Transcript: {transcript[:15000]}"""
        
        return StreamingResponse(stream_summary_generator(prompt, client), media_type="text/plain")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/video/upload")
async def summarize_video_file(file: UploadFile = File(...)):
    """Transcribe and stream summary of an uploaded video file."""
    try:
        content = await file.read()
        client = get_ai_client()
        transcript = transcribe_video_file(content, file.filename, client)
        
        prompt = f"Summarize this legal video transcript into structured KSLU exam notes:\n\n{transcript[:15000]}"
        return StreamingResponse(stream_summary_generator(prompt, client), media_type="text/plain")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/export/pdf")
async def export_pdf(req: PDFExportRequest):
    """Export academic content to a professional PDF."""
    try:
        pdf_buffer = generate_judicial_pdf(req.title, req.content)
        content = pdf_buffer.getvalue()
        pdf_buffer.close()
        
        return Response(
            content=content, 
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=Legaify_Export.pdf"}
        )
    except Exception as e:
        print(f"PDF Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/export/save-local")
async def export_local(req: PDFExportRequest):
    """Save content directly to the user's Downloads folder as PDF or MD."""
    # We'll default to 'pdf' as requested by the user
    result = save_content_locally(req.title, req.title, req.content, format="pdf")
    if result["status"] == "success":
        return result
    else:
        raise HTTPException(status_code=500, detail=result["message"])

@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "project": "Legaify"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str


@app.get("/")
def health_check():
    return {"status": "Vexa cloud backend is running"}


@app.post("/chat")
def chat(request: ChatRequest):
    response = client.responses.create(
        model="gpt-4.1-mini",
        instructions="""
You are Vexa, a friendly voice-first AI productivity assistant.
Keep replies short, natural, and useful.
""",
        input=request.message,
    )

    return {"reply": response.output_text}
from pathlib import Path
import os

from dotenv import load_dotenv
from openai import OpenAI


ROOT = Path(__file__).resolve().parents[1]

load_dotenv(ROOT / ".env")

api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    raise RuntimeError(
        "No se encontró OPENAI_API_KEY en .env"
    )

client = OpenAI(api_key=api_key)

print("Probando conexión con OpenAI...")

response = client.responses.create(
    model="gpt-5.6-luna",
    input=(
        "Responde únicamente: "
        "OpenAI conectado correctamente."
    ),
)

print()
print(response.output_text)
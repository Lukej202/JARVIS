
from dotenv import load_dotenv
from openai import OpenAI

print("JARVIS: Starting brain test...", flush=True)

load_dotenv()

client = OpenAI(timeout=30.0)

print("JARVIS: Contacting AI model...", flush=True)

response = client.responses.create(
    model="gpt-6-luna",
    instructions="You are JARVIS, a helpful personal AI assistant.",
    input="Introduce yourself as JARVIS."
)

print("JARVIS:", response.output_text)

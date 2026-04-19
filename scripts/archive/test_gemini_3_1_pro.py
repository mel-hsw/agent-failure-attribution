"""Smoke test: call gemini-3.1-pro-preview via Vertex AI."""
import os
from pathlib import Path

for line in Path(__file__).resolve().parents[1].joinpath(".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

from google import genai

client = genai.Client()
response = client.models.generate_content(
    model="gemini-3.1-pro-preview",
    contents="Reply with exactly: 'Vertex Gemini 3.1 Pro call succeeded.'",
)
print(response.text)
print(f"\nModel: gemini-3.1-pro-preview | Project: {os.environ['GOOGLE_CLOUD_PROJECT']} | Location: global")

import os
from google import genai
from dotenv import load_dotenv

load_dotenv('backend/.env')
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("Error: GEMINI_API_KEY not found in backend/.env")
else:
    try:
        client = genai.Client(api_key=api_key)
        print("Listing available models...")
        for model in client.models.list():
            print(f"Name: {model.name}, Supported Methods: {model.supported_generate_content_methods}")
    except Exception as e:
        print(f"Failed to list models: {e}")

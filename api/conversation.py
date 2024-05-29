from typing import List, Optional
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI()

class Conversation:
    def __init__(self, model: str = "gpt-4o", instruction: Optional[str] = None):
        self.model = model
        self.transcript = [{"role": "system", "content": instruction}] if instruction else []

    def message(self, message: str, images_urls: Optional[List[str]] = None) -> str:
        if images_urls:
            image_contents = [
                {"type": "image_url", "image_url" : {"url" : url}}
                for url in images_urls
            ]
            formatted_messages = {
                "role": "user",
                "content": [{"type": "text", "text": message}] + image_contents
            }
        else:
            formatted_messages = {"role": "user", "content": message}
            
        self.transcript.append(formatted_messages)
        
        response = client.chat.completions.create(
            model=self.model,
            messages=self.transcript
        )
        
        result = response.choices[0].message.content
        self.transcript.append({"role": "assistant", "content": result})
        return result
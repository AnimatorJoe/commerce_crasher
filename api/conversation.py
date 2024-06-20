import random
import yaml
from typing import Callable, List, Optional

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI()

class Conversation:
    def __init__(self, model: str = "gpt-4o", log_convo: bool = True, instruction: Optional[str] = None):
        self.model = model
        self.transcript = [{"role": "system", "content": instruction}] if instruction else []
        self.log_convo = log_convo
        self.color_code = f"\033[38;2;{random.randint(0, 255)};{random.randint(0, 255)};{random.randint(0, 255)}m"

    def __init__(self, transcript: list, model: str = "gpt-4o", log_convo: bool = True):
        self.__init__(model=model, log_convo=log_convo)
        self.transcript = transcript

    def __init__(self, transcript_path: str, model: str = "gpt-4o", log_convo: bool = True):
        data = yaml.safe_load(open(transcript_path, "r"))
        self.__init__(self, transcript=data, model=model, log_convo=log_convo)

    def message(self, message: str, images_urls: Optional[List[str]] = None) -> Optional[str]:
        if self.log_convo:
            print(f"{self.color_code}USER:\n{message}\n(images attachments - {images_urls})\033[0m")
            
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
        
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=self.transcript
            )
            
            result = response.choices[0].message.content
            self.transcript.append({"role": "assistant", "content": result})
            
            if self.log_convo:
                print(f"{self.color_code}ASSISTANT:\n{result}\033[0m")
                
            return result
        
        except Exception as e:
            print(f"An error occurred during conversation: {e}")
            
            return None
    
    def message_until_response_valid(
        self,
        valid: Callable[[str], bool],
        valid_criteria: str,
        message: str,
        images_urls: Optional[List[str]] = None,
        max_retries: int = 3
    ) -> Optional[str]:
        result = self.message(f"{message}\nthe answer should meet this criteria - {valid_criteria}", images_urls)
        
        if result is not None and valid(result):
            return result
        
        for _ in range(max_retries):
            result = self.message(f"the answer did not meet this criteria - {valid_criteria}; please answer again")
            if result is not None and valid(result):
                return result
        
        return None
    
    def log_conversation(self, file_path: str):
        with open(file_path, "a", encoding="utf-8") as file:
            yaml.dump(self.transcript, file, allow_unicode=True)
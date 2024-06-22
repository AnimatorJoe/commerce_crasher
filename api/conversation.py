import random
import base64
import httpx
import yaml
from typing import Callable, List, Tuple, Optional
from openai import OpenAI
from anthropic import Anthropic
from dotenv import load_dotenv
from functools import lru_cache

load_dotenv()

openai_client = OpenAI()
anthropic_client = Anthropic()

class Conversation:
    def __init__(self, model: str = "claude-3-sonnet-20240229", api: str = "anthropic", log_convo: bool = True, instruction: Optional[str] = None):
        assert api in ["openai", "anthropic"]
        self.model = model
        self.api = api
        self.transcript = [{"role": "system", "content": instruction}] if instruction else []
        self.log_convo = log_convo
        self.color_code = f"\033[38;2;{random.randint(0, 255)};{random.randint(0, 255)};{random.randint(0, 255)}m"

    @staticmethod
    def conversation_from_transcript(transcript: list, **kwargs) -> "Conversation":
        c = Conversation(**kwargs)
        c.transcript = transcript

    @staticmethod
    def conversation_from_file(transcript_path: str, **kwargs) -> "Conversation":
        with open(transcript_path, "r") as file:
            data = yaml.safe_load(file)
        return Conversation.conversation_from_transcript(transcript=data, **kwargs)

    @staticmethod
    def _get_image_data(url: str) -> Optional[Tuple[str, str]]:
        @lru_cache(maxsize=100)
        def cached_get_image_data(url: str) -> Optional[Tuple[str, str]]:
            try:
                response = httpx.get(url)
                response.raise_for_status()
                image_data = base64.b64encode(response.content).decode("utf-8")
                content_type = response.headers.get('Content-Type', '')
                return image_data, content_type
            except httpx.HTTPError as e:
                print(f"HTTP error occurred while fetching image: {e}")
                return None
            except Exception as e:
                print(f"An error occurred while fetching image: {e}")
                return None

        result = cached_get_image_data(url)
        if result is None:
            cached_get_image_data.cache_clear()
        return result

    def _get_anthropic_transcript(self) -> Tuple[list, Optional[str]]:
        system_message = next((msg['content'] for msg in self.transcript if msg['role'] == 'system'), None)
                
        messages = [msg for msg in self.transcript if msg['role'] != 'system']
        anthropic_messages = []
        
        for m in messages:
            assert type(m["content"]) in [str, list]
            if type(m["content"]) == str:
                anthropic_messages.append(m)
            elif type(m["content"]) == list:
                new_c = []
                image_count = 0
                for c in m["content"]:
                    assert c["type"] in ["text", "image_url"]
                    if c["type"] == "text":
                        new_c.append({"type": "text", "text": c["text"]})
                    elif c["type"] == "image_url":
                        image_count += 1
                        new_c.append({
                            "type": "text",
                            "text": f"Image {image_count}:"
                        })
                        data, content_type = Conversation._get_image_data(c["image_url"]["url"])
                        new_c.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": content_type,
                                "data": data
                            }
                        })
                
                new_m = {"role" : m["role"], "content": new_c}
                anthropic_messages.append(new_m)
        
        return anthropic_messages, system_message

    def message(self, message: str, images_urls: Optional[List[str]] = None) -> Optional[str]:
        if self.log_convo:
            print(f"{self.color_code}USER:\n{message}\n(images attachments - {images_urls})\033[0m")
            
        if images_urls:
            content = [{"type": "text", "text": message}] + [
                {"type": "image_url", "image_url": {"url": url}}
                for url in images_urls
            ]
        else:
            content = message
        self.transcript.append({"role": "user", "content": content})
        
        try:
            if self.api == "openai":
                response = openai_client.chat.completions.create(
                    model=self.model,
                    messages=self.transcript
                )
                result = response.choices[0].message.content 
            elif self.api == "anthropic":
                messages, system_message = self._get_anthropic_transcript()
                if system_message is not None:
                    response = anthropic_client.messages.create(
                        max_tokens=4096,
                        model=self.model,
                        messages=messages,
                        system=system_message
                    )
                else:
                    response = anthropic_client.messages.create(
                        max_tokens=4096,
                        model=self.model,
                        messages=messages
                    )
                result = response.content[0].text    
        except Exception as e:
            self.transcript = self.transcript[:-1]
            print(f"An error occurred during conversation: {e}")
            return None
        
        self.transcript.append({"role": "assistant", "content": result})
        
        if self.log_convo:
            print(f"{self.color_code}ASSISTANT:\n{result}\033[0m")
                
        return result
    
    def message_until_response_valid(
        self,
        valid: Callable[[str], bool],
        valid_criteria: str,
        message: str,
        images_urls: Optional[List[str]] = None,
        max_retries: int = 3
    ) -> Optional[str]:
        result = self.message(f"{message}\nanswer should meet criteria - {valid_criteria}", images_urls)
        
        if result is not None and valid(result):
            return result
        
        for _ in range(max_retries):
            result = self.message(f"answer did not meet criteria - {valid_criteria}; answer again")
            if result is not None and valid(result):
                return result
        
        return None
    
    def log_conversation(self, file_path: str):
        with open(file_path, "w", encoding="utf-8") as file:
            yaml.dump(self.transcript, file, allow_unicode=True)
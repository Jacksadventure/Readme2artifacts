"""AIInterface: Lazy-load model implementations for different backends."""

class AIInterface:
    def __init__(self, backend="openai", model: str="gpt-5-mini-2025-08-07"):
        if backend == "ollama":
            from models import OllamaModel
            self.model = OllamaModel(model)
        elif backend == "openai":
            from models import OpenAIModel
            self.model = OpenAIModel(model)
        elif backend == "gemini":
            from models import Gemini
            self.model = Gemini(model)
        elif backend == "claude":
            from models import ClaudeModel
            self.model = ClaudeModel(model)
        elif backend == "together":
            from models import TogetherModel
            self.model = TogetherModel(model)
        else:
            raise ValueError("Invalid backend")
        
    def get_response(self, prompt: str, text: str):
        return self.model.get_response(prompt, text)

 
"""الذكاء الاصطناعي المحلي في DPP: نماذج تعمل على الجهاز بلا إنترنت وبلا دفع.

المحرك مستقل عن الواجهة: `provider` للاتصال بالخدمة المحلية (Ollama أو LM Studio)،
`tools` لأدوات قراءة قاعدة البيانات، و`agent` للحلقة التي تجمع بينهما.
"""
from __future__ import annotations

from .agent import Agent
from .provider import AIConfig, AIError, detect, load_config, make_provider, save_config

__all__ = ["Agent", "AIConfig", "AIError", "detect", "load_config", "make_provider", "save_config"]

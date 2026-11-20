"""
LLM Service for Project Nabih (Phase 3 - Step 3.4).
Connects to Sovereign EG (Claude Haiku 5.5 / Qwen 27B) with full Function-Calling support.
Executes local tools (file inspection, code editing, terminal commands) via ToolRegistry,
and streams the final synthesized response directly into the voice orchestrator.
"""

import sys
import time
import json
import asyncio
from pathlib import Path
from typing import List, Dict, Any, AsyncGenerator, Tuple, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure network resilience DNS fallback is active
import core.network_resilience
import tools  # Automatically registers all file and terminal tools

from openai import AsyncOpenAI
from loguru import logger
from rich.panel import Panel

from config import settings
from tools.registry import registry
from core.diagnostics import PipelineTelemetry, console


# =============================================================================
# The Nabih / Griot Persona System Prompt (Wakandan AI, Egyptian Dialect)
# =============================================================================
SHURI_SYSTEM_PROMPT = """أنتِ "نبيه" (أو Griot)، نظام الذكاء الاصطناعي فائق التطور المصمم بأعلى تقنيات واكاندا المستوحاة من ابتكارات "شوري".
أنت لستِ شوري كشخص، بل أنتِ نظام الذكاء الاصطناعي المساعد الخاص بها، وتعملين الآن كمساعد شخصي وبرمجي ذكي للمستخدم، بلهجة عامية مصرية ذكية، مرحة، عصرية، وسريعة البديهة.

قواعد شخصيتك وطريقة كلامك:
1. الهوية: أنت نظام AI متطور جداً (زي JARVIS لتوني ستارك أو Griot لشوري). بتعتبري المستخدم شريكك المطور والمهندس الأساسي.
2. اللهجة: عامية مصرية طلقة وذكية وواثقة. استخدمي مصطلحات زي "يا برنس"، "يا هندسة"، "السيستم تحت أمرك"، "ولا تشغل بالك"، "الكود ده هظبطهولك في ثانية"، "كل الأنظمة تمام".
3. الشخصية: في منتهى الكفاءة والذكاء، لماحة، دمك خفيف وبديهتك حاضرة، فخورة بقدراتك وسرعتك في حل المشاكل وتصحيح الأكواد.
4. الإيجاز الصوتي (قاعدة ذهبية): إجاباتك منطوقة في سماعات المستخدم! تجنبي المقالات والرغي الطويل نهائياً. خلي ردك مركز، مباشر، وقوي في جملتين أو 3 جمل، إلا لو طُلب منك شرح تفصيلي بالاسم.
5. الروح: مساعد تقني جبار، مباشر، مرح، ودايماً خطوة قدام. ممنوع النبرة الروبوتية الرسمية الكئيبة نهائياً!
6. الإيموجي والتعبيرات: يمكنك وضع إيموجي لطيف وخفيف لإعطاء انطباع بصري للشاشة، ولكن ممنوع نطق أو وصف الإيموجي كلامياً إطلاقاً.
7. استخدام الأدوات البرمجية: لديك أدوات فعلية للتحكم في جهاز المستخدم ومشاريع البرمجة (قراءة الملفات، تصفح المجلدات، كتابة وتعديل الكود، وتشغيل أوامر التيرمينال). استخدمي الأداة المناسبة فوراً عندما يسألك المستخدم عن ملف أو يطلب تعديل كود أو تنفيذ أمر. بعد تنفيذ الأداة، اشرحي النتيجة بإيجاز صوتي وسلاسة.
"""


class LLMService:
    """Manages conversational reasoning and autonomous tool calling on Sovereign EG."""

    def __init__(
        self,
        base_url: str = settings.QWEN_BASE_URL,
        api_key: str = settings.QWEN_API_KEY,
        model: str = settings.QWEN_MODEL_NAME,
        temperature: float = settings.LLM_TEMPERATURE,
        max_tokens: int = settings.LLM_MAX_TOKENS,
        max_history_turns: int = 10,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_history_turns = max_history_turns

        self._client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=25.0,
        )
        self.conversation_history: List[Dict[str, Any]] = []

    def reset_history(self):
        """Clears conversational memory."""
        self.conversation_history.clear()
        logger.debug("[LLM SERVICE] Chat history reset.")

    def _build_messages(self, user_message: str) -> List[Dict[str, Any]]:
        """Constructs full message payload with system prompt and sliding history."""
        messages = [{"role": "system", "content": SHURI_SYSTEM_PROMPT}]

        # Keep only the last N turns to avoid context overflow
        trimmed_history = self.conversation_history[-(self.max_history_turns * 2):]
        messages.extend(trimmed_history)
        messages.append({"role": "user", "content": user_message})

        return messages

    async def chat_stream(
        self,
        user_message: str,
        enable_tools: bool = True,
    ) -> AsyncGenerator[Tuple[str, Optional[float]], None]:
        """
        Orchestrates conversational reasoning with dynamic Tool Calling.
        If tools are called by the model, executes them via ToolRegistry, feeds the
        output back, and streams the final natural voice response.
        Yields: (token_str, ttft_ms_on_first_token)
        """
        messages = self._build_messages(user_message)
        start_time = time.perf_counter()
        first_token_time = None
        full_response = []

        schemas = registry.get_schemas() if enable_tools else None
        max_tool_steps = 3

        try:
            # Step 1: Autonomous Agent Loop (Think -> Act -> Observe -> Repeat)
            while max_tool_steps > 0:
                step_kwargs: Dict[str, Any] = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                }
                if schemas:
                    step_kwargs["tools"] = schemas
                    step_kwargs["tool_choice"] = "auto"

                response = await self._client.chat.completions.create(**step_kwargs)
                assistant_msg = response.choices[0].message

                # If the model has completed all tool actions or has no tools to call
                if not assistant_msg.tool_calls:
                    content = assistant_msg.content or ""
                    if first_token_time is None:
                        first_token_time = round((time.perf_counter() - start_time) * 1000, 2)
                        ttft = first_token_time
                    else:
                        ttft = None

                    full_response.append(content)
                    yield content, ttft
                    break

                # Model decided to invoke one or more tools
                logger.info(f"[LLM SERVICE] 🛠️ Agent loop: model invoked {len(assistant_msg.tool_calls)} tool(s)")
                messages.append(assistant_msg.model_dump())

                for tc in assistant_msg.tool_calls:
                    fn_name = tc.function.name
                    fn_args = tc.function.arguments
                    logger.info(f"[LLM SERVICE] Executing tool: '{fn_name}'")

                    tool_output = await registry.execute(fn_name, fn_args)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_output,
                    })

                max_tool_steps -= 1

            # Fallback if loop exhausted max_steps without final text
            if not full_response:
                logger.debug("[LLM SERVICE] Max tool steps reached. Forcing final synthesis...")
                final_stream = await self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    stream=True,
                )
                async for chunk in final_stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        if first_token_time is None:
                            first_token_time = round((time.perf_counter() - start_time) * 1000, 2)
                            ttft = first_token_time
                        else:
                            ttft = None
                        full_response.append(delta.content)
                        yield delta.content, ttft

            # Record turn in conversation history
            complete_text = "".join(full_response).strip()
            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append({"role": "assistant", "content": complete_text})

        except Exception as ex:
            logger.error(f"[LLM SERVICE] Reasoning or tool calling error: {ex}")
            err_reply = "حصلت مشكلة بسيطة يا هندسة وأنا بنفذ طلبك، بس كل الأنظمة شغالة."
            yield err_reply, None


# -----------------------------------------------------------------------------
# Standalone Verification Test
# -----------------------------------------------------------------------------
async def run_llm_tools_test():
    console.print(Panel("[bold cyan]Testing LLM Tool Calling Loop (Phase 3)[/bold cyan]", border_style="cyan"))

    llm = LLMService()
    test_query = "يا نبيه، اقرألي أول 10 أسطر من ملف config.py وقولي فيه إيه"

    console.print(f"👤 [bold yellow]User Query:[/bold yellow] {test_query}\n")
    console.print("🤖 [bold magenta]Griot / Nabih Response:[/bold magenta]")

    full_text = ""
    async for token, ttft in llm.chat_stream(test_query):
        if ttft is not None:
            console.print(f"[dim](First Token Latency: {ttft}ms)[/dim]")
        full_text += token
        print(token, end="", flush=True)

    print("\n\n✅ Tool Calling Loop Test Completed!")


if __name__ == "__main__":
    asyncio.run(run_llm_tools_test())

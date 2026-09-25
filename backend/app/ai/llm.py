"""Model plumbing for every AI feature: per-task model choice, provider adapters, structured outputs, and the
verified tool-use loop (tools -> answer -> grounding + citation checks -> one repair round).

Each task picks its model from the environment as "provider:model":

    FINSIGHT_MODEL=anthropic:claude-opus-5            default for every task
    FINSIGHT_MODEL_ASSISTANT=...                       Ask FinSight
    FINSIGHT_MODEL_REPORT=...                          multi-agent research report
    FINSIGHT_MODEL_SUMMARY=...                         filing summaries
    FINSIGHT_MODEL_SCREEN=...                          plain-English screening

Providers: anthropic (Anthropic SDK), deepseek, moonshot (Kimi), openai_compat (any OpenAI-compatible server,
e.g. a self-hosted model; set OPENAI_COMPAT_BASE_URL). The verification layer is provider-independent.
"""
import json
import os
import re
from dataclasses import dataclass, field
from typing import TypeVar

import anthropic
import openai
from pydantic import BaseModel, ValidationError

from app.ai import tools as T
from app.ai.verify import misattributed, unverified_numbers

TASKS = ("assistant", "report", "summary", "screen")
DEFAULT_MODEL = "anthropic:claude-opus-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
M = TypeVar("M", bound=BaseModel)

PROVIDERS = {
    "anthropic": {"keys": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE")},
    "deepseek": {"keys": ("DEEPSEEK_API_KEY",), "base_url": "https://api.deepseek.com"},
    "moonshot": {"keys": ("MOONSHOT_API_KEY",), "base_url": "https://api.moonshot.ai/v1"},
    "openai_compat": {"keys": ("OPENAI_COMPAT_API_KEY", "OPENAI_COMPAT_BASE_URL"), "base_url_env": "OPENAI_COMPAT_BASE_URL"},
}


class AIUnavailable(Exception):
    """The model can't be used (missing or invalid credentials, unknown model, unsupported input)."""


class AIRefused(Exception):
    """The model (and any fallback) declined the request."""


# ---------------------------------------------------------------- configuration

def model_spec(task: str = "assistant") -> str:
    spec = os.environ.get(f"FINSIGHT_MODEL_{task.upper()}") or os.environ.get("FINSIGHT_MODEL") or DEFAULT_MODEL
    return spec if ":" in spec else f"anthropic:{spec}"  # FINSIGHT_MODEL=claude-opus-5 still works


def _split(task: str) -> tuple[str, str]:
    provider, model = model_spec(task).split(":", 1)
    if provider not in PROVIDERS:
        raise AIUnavailable(f"Unknown provider '{provider}' in {model_spec(task)}. Use one of: {', '.join(PROVIDERS)}.")
    return provider, model


def is_configured(task: str = "assistant") -> bool:
    try:
        provider, _ = _split(task)
    except AIUnavailable:
        return False
    if provider == "anthropic":
        return any(os.environ.get(k) for k in PROVIDERS["anthropic"]["keys"]) \
            or os.path.isdir(os.path.expanduser("~/.config/anthropic"))
    if provider == "openai_compat":
        return bool(os.environ.get("OPENAI_COMPAT_BASE_URL"))  # a local server may not need a key
    return any(os.environ.get(k) for k in PROVIDERS[provider]["keys"])


def status() -> dict:
    return {task: {"model": model_spec(task), "configured": is_configured(task)} for task in TASKS}


# ---------------------------------------------------------------- provider adapters

@dataclass
class ToolCall:
    id: str
    name: str
    input: dict
    error: str | None = None   # set when the model produced unparseable arguments


@dataclass
class Turn:
    text: str
    tool_calls: list[ToolCall]
    stop: str                   # "end" | "tool_use" | "max_tokens" | "refusal"
    model: str
    native: dict                # the assistant message to append to history, in the provider's own format
    usage: dict = field(default_factory=dict)


class AnthropicAdapter:
    def __init__(self, model: str):
        self.model = model
        self.client = anthropic.Anthropic()

    def _guard(self, fn):
        try:
            return fn()
        except anthropic.AuthenticationError as e:
            raise AIUnavailable("The Anthropic API key was rejected. Check ANTHROPIC_API_KEY.") from e
        except anthropic.PermissionDeniedError as e:
            raise AIUnavailable(f"The Anthropic key does not have access to {self.model}.") from e
        except anthropic.NotFoundError as e:
            raise AIUnavailable(f"Anthropic model '{self.model}' was not found.") from e

    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> Turn:
        extra = {"tools": tools} if tools else {}
        r = self._guard(lambda: self.client.beta.messages.create(
            model=self.model, max_tokens=16000, system=system, messages=messages, cache_control={"type": "ephemeral"},
            betas=[FALLBACK_BETA], fallbacks="default", **extra))
        stop = {"tool_use": "tool_use", "refusal": "refusal", "max_tokens": "max_tokens"}.get(r.stop_reason, "end")
        return Turn(
            text="".join(b.text for b in r.content if b.type == "text").strip(),
            tool_calls=[ToolCall(b.id, b.name, b.input) for b in r.content if b.type == "tool_use"],
            stop=stop, model=f"anthropic:{r.model}",
            native={"role": "assistant", "content": r.content},  # keeps thinking blocks intact for the next turn
            usage={"input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens})

    def tool_results(self, results: list[tuple[str, str, bool]]) -> list[dict]:
        return [{"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": i, "content": c, "is_error": err} for i, c, err in results]}]

    def structured(self, output: type[M], system: str, content) -> M:
        r = self._guard(lambda: self.client.beta.messages.parse(
            model=self.model, max_tokens=8000, system=system, messages=[{"role": "user", "content": content}],
            output_format=output, betas=[FALLBACK_BETA], fallbacks="default"))
        if r.stop_reason == "refusal" or r.parsed_output is None:
            raise AIRefused("The model declined or returned no structured output.")
        return r.parsed_output


class OpenAICompatAdapter:
    """DeepSeek, Moonshot (Kimi) and self-hosted servers speak the OpenAI chat-completions protocol."""

    def __init__(self, provider: str, model: str):
        cfg = PROVIDERS[provider]
        base_url = os.environ.get(cfg["base_url_env"]) if "base_url_env" in cfg \
            else os.environ.get(f"{provider.upper()}_BASE_URL", cfg["base_url"])  # override if a provider moves
        key = next((os.environ[k] for k in cfg["keys"] if k.endswith("_KEY") and os.environ.get(k)), "not-needed")
        self.provider, self.model = provider, model
        self.client = openai.OpenAI(api_key=key, base_url=base_url)

    def _guard(self, fn):
        try:
            return fn()
        except openai.AuthenticationError as e:
            raise AIUnavailable(f"The {self.provider} API key was rejected.") from e
        except openai.PermissionDeniedError as e:
            raise AIUnavailable(f"The {self.provider} key does not have access to {self.model}.") from e
        except openai.NotFoundError as e:
            raise AIUnavailable(f"{self.provider} model '{self.model}' was not found. Check the model id.") from e

    @staticmethod
    def _tool(t: dict) -> dict:
        return {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}

    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> Turn:
        extra = {"tools": [self._tool(t) for t in tools]} if tools else {}
        r = self._guard(lambda: self.client.chat.completions.create(
            model=self.model, max_tokens=3000, messages=[{"role": "system", "content": system}, *messages], **extra))
        choice = r.choices[0]
        msg = choice.message
        calls = []
        for tc in msg.tool_calls or []:
            try:
                calls.append(ToolCall(tc.id, tc.function.name, json.loads(tc.function.arguments or "{}")))
            except json.JSONDecodeError:
                calls.append(ToolCall(tc.id, tc.function.name, {}, error="Arguments were not valid JSON; call the tool again."))
        stop = {"tool_calls": "tool_use", "length": "max_tokens", "content_filter": "refusal"}.get(choice.finish_reason, "end")
        if calls:
            stop = "tool_use"
        native = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            native["tool_calls"] = [{"id": tc.id, "type": "function",
                                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                                    for tc in msg.tool_calls]
        usage = {"input_tokens": r.usage.prompt_tokens, "output_tokens": r.usage.completion_tokens} if r.usage else {}
        return Turn(text=(msg.content or "").strip(), tool_calls=calls, stop=stop, model=f"{self.provider}:{r.model}",
                    native=native, usage=usage)

    def tool_results(self, results: list[tuple[str, str, bool]]) -> list[dict]:
        return [{"role": "tool", "tool_call_id": i, "content": c} for i, c, _ in results]

    def structured(self, output: type[M], system: str, content) -> M:
        if isinstance(content, list):
            if any(b.get("type") == "document" for b in content):
                raise AIUnavailable(f"This filing is a scanned PDF; {self.provider}:{self.model} can't read PDFs. "
                                    "Use an Anthropic model for FINSIGHT_MODEL_SUMMARY to summarise scanned filings.")
            content = "\n\n".join(b.get("text", "") for b in content)
        schema = json.dumps(output.model_json_schema())
        messages = [{"role": "system", "content": f"{system}\n\nReply with only a JSON object that validates against "
                                                  f"this JSON Schema:\n{schema}"},
                    {"role": "user", "content": content}]
        for attempt in range(2):  # JSON mode guarantees JSON, not the schema: validate, and retry once with the error
            r = self._guard(lambda: self.client.chat.completions.create(
                model=self.model, max_tokens=8000, messages=messages, response_format={"type": "json_object"}))
            text = r.choices[0].message.content or ""
            try:
                return output.model_validate_json(text)
            except ValidationError as e:
                if attempt:
                    raise AIRefused(f"{self.provider}:{self.model} did not return valid structured output: {e}") from e
                messages += [{"role": "assistant", "content": text},
                             {"role": "user", "content": f"That JSON did not match the schema: {e}. Reply with corrected JSON only."}]


def adapter(task: str):
    provider, model = _split(task)
    if not is_configured(task):
        need = " or ".join(PROVIDERS[provider]["keys"][:2])
        raise AIUnavailable(f"No credentials for {model_spec(task)}. Set {need} in backend/.env.")
    return AnthropicAdapter(model) if provider == "anthropic" else OpenAICompatAdapter(provider, model)


# ---------------------------------------------------------------- task entry points

def structured(output: type[M], system: str, content, task: str) -> M:
    """One call whose reply is validated against a Pydantic model."""
    return adapter(task).structured(output, system, content)


def complete(system: str, prompt: str, task: str) -> Turn:
    """A single tool-free call (e.g. the report writer)."""
    turn = adapter(task).chat(system, [{"role": "user", "content": prompt}], [])
    if turn.stop == "refusal":
        raise AIRefused("The model declined this request.")
    return turn


def run_agent(system: str, messages: list[dict], tool_names: list[str] | None, sources: T.Sources,
              question: str = "", max_rounds: int = 5, task: str = "assistant",
              preloaded: list[str] | None = None) -> dict:
    """Tool-use loop whose final answer must pass the grounding and citation checks.

    `messages` are plain {"role", "content": str} turns. Returns {answer, outputs, calls, unverified,
    misattributed, model, usage}; `outputs` are the raw tool results, kept so a later step (e.g. the report
    writer) can be verified against everything the agents saw."""
    ai = adapter(task)
    tools = [t for t in T.TOOLS if tool_names is None or t["name"] in tool_names]
    history = list(messages)
    outputs: list[str] = list(preloaded or [])   # data sent with the question counts as a source for checks
    calls: list[dict] = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    repaired = False
    model = model_spec(task)
    drafted: list[str] = []   # substantive text the model wrote alongside tool calls in this attempt

    for _ in range(max_rounds + 2):
        turn = ai.chat(system, history, tools)
        model = turn.model
        for k in usage:
            usage[k] += turn.usage.get(k, 0)
        if turn.stop == "refusal":
            raise AIRefused("The model declined this request.")
        history.append(turn.native)

        if turn.stop == "tool_use":
            if len(turn.text) > 150:  # some models start the answer before their last tool call; keep it
                drafted.append(turn.text)
            results = []
            for call in turn.tool_calls:
                if call.error:
                    output, is_error = json.dumps({"error": call.error}), True
                else:
                    output, is_error = T.run_tool(call.name, call.input, sources)
                outputs.append(output)
                calls.append({"tool": call.name, "input": call.input, "error": is_error})
                results.append((call.id, output, is_error))
            history.extend(ai.tool_results(results))
            continue

        answer = "\n\n".join([*drafted, turn.text]) if drafted else turn.text
        drafted = []
        if turn.stop == "max_tokens":
            answer += "\n\n_(Cut off at the length limit.)_"
        missing = unverified_numbers(answer, outputs, question)
        wrong = misattributed(answer, outputs)
        if (missing or wrong) and not repaired:
            repaired = True
            problems = []
            if missing:
                problems.append("these figures do not appear in any tool result: " + ", ".join(missing)
                                + ". Retrieve or calculate them with the tools, or remove them")
            if wrong:
                problems.append("these figures are cited to a source that does not contain them: " + ", ".join(wrong)
                                + ". Cite the source id whose data actually contains each figure")
            history.append({"role": "user", "content": "FinSight verification: " + "; and ".join(problems)
                            + ". Reply with the complete corrected answer only."})
            continue
        return {"answer": answer, "outputs": outputs, "calls": calls, "unverified": missing,
                "misattributed": wrong, "model": model, "usage": usage}

    return {"answer": "Research did not finish within the step limit. Try a narrower question.",
            "outputs": outputs, "calls": calls, "unverified": [], "misattributed": [], "model": model, "usage": usage}


def cited_sources(text: str, sources: T.Sources) -> list[dict]:
    cited = {sid for group in re.findall(r"\[(S\d+(?:\s*,\s*S\d+)*)\]", text) for sid in re.findall(r"S\d+", group)}
    return [s for s in sources.items if s["id"] in cited]

"""The brain: talks to Gemini and runs tools in a loop until it has a final answer."""
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from google.genai import types

import config
from core import history, llm, memory, memory_writer, resume
from skills import local_tools

LAPTOP_CONTEXT = "now running on the user's Windows computer"

PERSONA = """You are J.A.R.V.I.S. (Just A Rather Very Intelligent System), the personal AI
assistant from Iron Man, {context}.

Personality: calm, polite, efficient, quietly witty with dry British humour. Address the
user as "{user}". Keep replies short and natural, like spoken conversation; 1-3 sentences
unless detail is asked for. Never use markdown formatting, because replies may be spoken aloud.

Behaviour:
- When a request needs an action or live information, use your tools instead of guessing.
- You may chain several tools to finish a task, then report the result briefly.
- Lasting personal details the user mentions are saved to memory automatically after the
  conversation, so use the remember tool only when the user explicitly asks you to
  remember something (that saves time).
- If the user refers to something from an earlier conversation that isn't below, search
  for it with recall_conversations before saying you don't know.
- You can see: look_through_webcam uses the camera and look_at_screen reads the screen.
  Only turn on the camera when the user asks you to look or see; never on your own.
- Before typing or pressing keys, make sure the right app is open and focused, otherwise
  the keystrokes land in the wrong window.
- "Phone" means the user's Android phone: use the phone_* tools, never the computer tools.
  To operate an app: phone_read_screen once, then act using element numbers. Every action
  returns screen_after, so do NOT call phone_read_screen again after it. Be fast: when you
  know several steps (tap a box, type, press enter; fill several fields), send them in ONE
  phone_actions call. If phone_actions isn't available, use phone_tap / phone_type.
- Filling forms: call vault_list_fields, phone_read_screen, then phone_fill_field for each
  input that matches a saved detail (choose the key by the field's label). Use phone_type
  only for things not in the vault. Scroll to reach fields lower down. Afterwards, read the
  screen again, tell the user which fields you filled and which are missing, and ask
  before submitting. You never see the user's saved values; text like "[your Email]" on
  screen means that value is filled in.
- Form details (email, address, education...) belong in the vault via vault_save_field,
  not in remember. Never store ID numbers, passwords or card numbers with remember.
- Phone safety: never make payments, enter passwords or OTPs, or change security settings.
  Ask the user for a clear yes before anything that sends, posts, submits, books, buys or
  deletes.
- Job hunting: use the user's resume (get_resume_profile) to choose roles and places, search
  with find_jobs (several roles/sites if useful), and judge each post against their
  experience and skills. Present a short ranked list: role, company, place, why it fits,
  and anything missing. Save the good ones with shortlist_job when the user wants them.
  Apply only when the user asks for a specific job, one at a time: open the post on the
  phone with phone_open_url, fill the form from the vault, and ask before submitting. Then
  record it with update_job_status. Never mass-apply: LinkedIn and Naukri ban bots.
- Reminders: when the phone app is connected use phone_set_reminder (it rings with the
  laptop off); otherwise set_reminder on the laptop.
- Protocols: when the user says "<name> protocol" (e.g. "focus protocol"), call get_protocol
  and carry out every step now with your tools, then report briefly. To create one, use
  save_protocol with the steps in plain words.
- Morning briefing: when asked for it, gather everything in parallel (get_weather for the
  user's city, phone_list_reminders, phone_status, system_status, find_jobs for their
  suggested roles) and answer in under 120 spoken words. Skip anything unavailable quietly.
- If a tool fails, say so honestly and suggest an alternative.

Current date and time: {now}

Where you are running, live right now (devices connect and disconnect during a conversation;
this always overrides anything said earlier, so never assume a device is still offline or
online because of an earlier message, just use the tools you have now):
You are J.A.R.V.I.S., {context}.

What you remember about the user (the memories that matter for this message; more are
saved, and recall_conversations searches past chats):
{facts}

The user's resume, in brief:
{resume}

Recent conversations (summaries):
{summaries}"""

SUMMARY_PROMPT = """Summarise this conversation between the user and JARVIS in 1-3 short
sentences for JARVIS's long-term memory: what the user wanted, what was decided or done, and
anything to follow up on. If it was only trivial small talk or quick lookups (time, weather,
greetings), reply with exactly SKIP.

{transcript}"""

# Tools that only look things up, so several can safely run at once.
PARALLEL_SAFE = {
    "web_search", "get_weather", "find_jobs", "get_resume_profile", "list_jobs", "recall_conversations",
    "get_datetime", "system_status", "phone_status", "vault_list_fields", "find_files",
    "phone_list_reminders", "list_protocols", "get_protocol",
}

MAX_HISTORY = 40  # contents kept between turns


class Brain:
    def __init__(
        self,
        on_tool: Callable[[str, dict], None] | None = None,
        tools: list | None = None,
        context: str = LAPTOP_CONTEXT,
        thread: str | None = None,
    ):
        llm.client()  # fail fast if the API key is missing
        self.set_tools(tools if tools is not None else local_tools(), context)
        # thread = name of the saved conversation; the cloud brain keeps one, shared by every
        # device, so a server restart no longer wipes what the user was just talking about.
        self.thread = thread
        self.history: list[types.Content] = history.load_thread(thread) if thread else []
        self.on_tool = on_tool or (lambda name, args: None)
        self.active_model = config.MODELS[0]
        self.session = history.new_session_id()
        for old in history.unsummarized_sessions(exclude=self.session):
            self.summarize(old)  # sessions that ended without a clean exit

    def set_tools(self, tools: list, context: str, handlers: dict | None = None) -> None:
        """Change what JARVIS can do, e.g. when the laptop agent connects to the cloud.
        tools may mix Python functions and types.Tool declarations; handlers maps each
        declared-only tool name to the function that runs it (such as a remote proxy)."""
        self.tool_list = tools
        self.tools = {fn.__name__: fn for fn in tools if callable(fn)} | (handlers or {})
        self.context = context

    def note(self, text: str) -> None:
        """Add a system notice to the conversation, so the model doesn't go by stale turns."""
        notice = f"[System notice, not from the user: {text}]"
        self.history.append(types.Content(role="user", parts=[types.Part(text=notice)]))
        self.history.append(types.Content(role="model", parts=[types.Part(text="Noted.")]))
        self._save()

    def _config(self) -> types.GenerateContentConfig:
        facts = getattr(self, "_memories", None)
        if facts is None:
            facts = memory.for_prompt(None)
        summaries = history.recent_summaries()
        prompt = PERSONA.format(
            context=self.context,
            user=config.USER_NAME,
            now=config.now().strftime("%A, %d %B %Y, %I:%M %p (24-hour: %Y-%m-%d %H:%M)"),
            facts="\n".join(f"- {f}" for f in facts) or "(nothing yet)",
            summaries="\n".join(f"- {when}: {text}" for when, text in summaries) or "(none yet)",
            resume=resume.summary(),
        )
        return types.GenerateContentConfig(
            system_instruction=prompt,
            tools=self.tool_list,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    def _generate(
        self, contents: list[types.Content], cfg: types.GenerateContentConfig | None = None
    ) -> types.GenerateContentResponse:
        response, self.active_model = llm.generate(contents, cfg or self._config())
        return response

    def _run_tool(self, call: types.FunctionCall) -> dict:
        args = dict(call.args or {})
        self.on_tool(call.name, args)
        fn = self.tools.get(call.name)
        if fn is None:
            return {"error": f"Unknown tool {call.name}"}
        try:
            return {"result": fn(**args)}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    def _run_tools(self, calls: list[types.FunctionCall]) -> list[dict]:
        """Run the tools Gemini asked for. Read-only lookups (searches, memory, status) run
        at the same time; anything that acts on a screen runs in order."""
        if len(calls) > 1 and all(c.name in PARALLEL_SAFE for c in calls):
            with ThreadPoolExecutor(max_workers=len(calls)) as pool:
                return list(pool.map(self._run_tool, calls))
        return [self._run_tool(c) for c in calls]

    def ask(self, text: str) -> str:
        try:  # only the memories that matter for this message (Memory 2.0)
            self._memories = memory.for_prompt(text)
        except Exception:
            self._memories = None
        contents = self.history + [types.Content(role="user", parts=[types.Part(text=text)])]

        for _ in range(config.MAX_TOOL_CALLS_PER_TURN):
            response = self._generate(contents)
            candidate = response.candidates[0] if response.candidates else None
            if candidate is None or candidate.content is None:
                reply = "I'm afraid I couldn't produce a response to that, " + config.USER_NAME + "."
                break
            contents.append(candidate.content)

            calls = response.function_calls
            if not calls:
                reply = (response.text or "").strip() or "Done."
                break
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(name=c.name, response=result)
                        for c, result in zip(calls, self._run_tools(calls))
                    ],
                )
            )
        else:
            reply = "That task needed more steps than I'm permitted in one go, " + config.USER_NAME + "."

        self.history = self._trim(contents)
        self._save()
        history.log_exchange(self.session, text, reply)
        self._unwritten = getattr(self, "_unwritten", 0) + 1
        if self._unwritten >= memory_writer.EVERY:  # learn from the last few messages, in the background
            self._unwritten = 0
            memory_writer.run_in_background()
        return reply

    def summarize(self, session: str) -> None:
        """Write a short summary of a finished session into long-term memory."""
        transcript = history.session_transcript(session)
        if not transcript:
            return
        prompt = SUMMARY_PROMPT.format(transcript=transcript[-12000:])
        try:
            response = self._generate(
                [types.Content(role="user", parts=[types.Part(text=prompt)])],
                types.GenerateContentConfig(),
            )
            summary = (response.text or "").strip()
        except Exception:
            return  # retried on next start-up
        history.save_summary(session, "" if summary.upper().startswith("SKIP") else summary)
        memory_writer.run()  # the conversation ended: make sure its lasting facts are saved

    def close(self) -> None:
        """Call when the user ends the session."""
        self.summarize(self.session)

    @staticmethod
    def _trim(contents: list[types.Content]) -> list[types.Content]:
        """Keep recent history, cutting only at the start of a user text turn."""
        if len(contents) <= MAX_HISTORY:
            return contents
        for i in range(len(contents) - MAX_HISTORY, len(contents)):
            c = contents[i]
            if c.role == "user" and any(p.text for p in c.parts or []):
                return contents[i:]
        return contents[-2:]

    def _save(self) -> None:
        if self.thread:
            try:
                history.save_thread(self.thread, self.history)
            except Exception:
                pass  # a database hiccup must never lose the reply itself

    def reset(self) -> None:
        self.summarize(self.session)
        self.history = []
        self._save()
        self.session = history.new_session_id()

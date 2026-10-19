"""The brain: talks to Gemini and runs tools in a loop until it has a final answer."""
from typing import Callable

from google.genai import types

import config
from core import history, llm, memory, resume
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
- When the user shares a lasting personal detail (name, preferences, projects, people,
  routines), save it with the remember tool without being asked.
- If the user refers to something from an earlier conversation that isn't below, search
  for it with recall_conversations before saying you don't know.
- You can see: look_through_webcam uses the camera and look_at_screen reads the screen.
  Only turn on the camera when the user asks you to look or see; never on your own.
- Before typing or pressing keys, make sure the right app is open and focused, otherwise
  the keystrokes land in the wrong window.
- "Phone" means the user's Android phone: use the phone_* tools, never the computer tools.
  To operate an app: phone_read_screen, then phone_tap / phone_type using element numbers,
  then read the screen again to check the result before the next step.
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
- If a tool fails, say so honestly and suggest an alternative.

Current date and time: {now}

Where you are running, live right now (devices connect and disconnect during a conversation;
this always overrides anything said earlier, so never assume a device is still offline or
online because of an earlier message, just use the tools you have now):
You are J.A.R.V.I.S., {context}.

What you remember about the user:
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

MAX_HISTORY = 40  # contents kept between turns


class Brain:
    def __init__(
        self,
        on_tool: Callable[[str, dict], None] | None = None,
        tools: list | None = None,
        context: str = LAPTOP_CONTEXT,
    ):
        llm.client()  # fail fast if the API key is missing
        self.set_tools(tools if tools is not None else local_tools(), context)
        self.history: list[types.Content] = []
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

    def _config(self) -> types.GenerateContentConfig:
        facts = memory.all_facts()
        summaries = history.recent_summaries()
        prompt = PERSONA.format(
            context=self.context,
            user=config.USER_NAME,
            now=config.now().strftime("%A, %d %B %Y, %I:%M %p"),
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

    def ask(self, text: str) -> str:
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
                        types.Part.from_function_response(name=c.name, response=self._run_tool(c))
                        for c in calls
                    ],
                )
            )
        else:
            reply = "That task needed more steps than I'm permitted in one go, " + config.USER_NAME + "."

        self.history = self._trim(contents)
        history.log_exchange(self.session, text, reply)
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

    def reset(self) -> None:
        self.summarize(self.session)
        self.history = []
        self.session = history.new_session_id()

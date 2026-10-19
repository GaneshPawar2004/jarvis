# Handoff prompt: JARVIS project

You are taking over an in-progress software project: a personal "J.A.R.V.I.S." assistant
(inspired by Tony Stark's AI in Iron Man) running on the user's Windows 11 PC. Phase 1 is
complete and tested. Your job is to continue with Phase 2 and beyond. Read this whole prompt
before writing any code.

## About the user
- Building this as a personal project. Communicates in simple English and may prefer Hindi/Hinglish.
- Wants movie-style JARVIS capabilities, connected to an AI model.
- Is using a **free** Gemini API key (Google AI Studio). Do not introduce paid services
  without asking first.

## Environment
- OS: Windows 11. Project folder: `D:\jarvis`
- Python 3.12.10 with a virtualenv at `D:\jarvis\.venv`. Always use `.venv\Scripts\python`.
- Node 22 is also installed, but the project is Python.
- Installed packages: `google-genai` (2.31.0), `python-dotenv`, `psutil`, `ddgs`, `rich`
  (listed in `requirements.txt`).
- `D:\jarvis\.env` contains `GEMINI_API_KEY=...`. **Never print, log or echo the key's value.**
  To inspect `.env`, show only the variable names.

## Current architecture (Phase 1: done)
```
D:\jarvis
  main.py              entry point (sets UTF-8 stdout, runs interfaces.cli)
  jarvis.bat           double-click launcher
  config.py            loads .env; MODELS fallback list; USER_NAME ("sir"); MEMORY_FILE; MAX_TOOL_CALLS_PER_TURN
  core/brain.py        Brain class: persona system prompt + manual tool-calling loop over Gemini
  core/memory.py       long-term facts in data/memory.json (add_fact / remove_fact / all_facts)
  skills/__init__.py   ALL_TOOLS registry: every function listed here is exposed to the model
  skills/system.py     get_datetime, system_status (psutil), open_application, open_website
  skills/web.py        web_search (ddgs / DuckDuckGo, top 5 results)
  skills/memory.py     remember, forget (the model calls these itself)
  interfaces/cli.py    rich-based terminal chat; shows "⚙ tool(args)" lines; /reset, /exit
  .gitignore           ignores .env, .venv/, __pycache__/, data/
```

### Key design decisions (keep them)
1. **Manual tool loop, not the SDK's automatic function calling.** `Brain.ask()` calls
   `generate_content` with `tools=ALL_TOOLS` and `AutomaticFunctionCallingConfig(disable=True)`.
   It appends `candidate.content` **unchanged** (this preserves Gemini thought signatures),
   runs each function call, and appends the results as a `role="user"` Content made of
   `Part.from_function_response` parts. The loop repeats until there are no function calls,
   capped by `MAX_TOOL_CALLS_PER_TURN`.
2. **Model fallback.** `Brain._generate` tries `config.MODELS` in order:
   `gemini-3.5-flash`, then `gemini-flash-latest`, then `gemini-flash-lite-latest`. On HTTP
   429/500/503/504/404 it moves to the next model, and makes 2 passes with a backoff. On the
   free tier, 503 "high demand" errors are common. The list can be overridden with the
   `JARVIS_MODELS` env var.
3. **Skills are plain typed Python functions with Google-style docstrings.** The SDK builds
   the tool schema from the signature and docstring, so write clear docstrings and use
   simple types. To add a skill, write the function, then add it to `ALL_TOOLS`.
4. **The system prompt is rebuilt every call** with the current time and all remembered facts.
   The persona is calm, polite, British-butler wit, and addresses the user as "sir". Replies
   are short and contain **no markdown**, because they will be spoken aloud.
5. **History trimming** (`MAX_HISTORY = 40`) cuts only at the start of a user *text* turn, so
   a function call is never separated from its response.
6. `Brain(on_tool=callback)` lets each interface display tool activity. Keep the brain
   independent of any UI so that the CLI, voice and HUD can all reuse it.

### Verified working (tested)
- Time, date and system status (CPU, RAM, disk, battery).
- Live web search answering a current-events question.
- Multi-turn context within a session.
- The model saves facts on its own, and memory persists across new `Brain` sessions.

### Not yet verified
- `open_application` and `open_website` were **not** run during testing, so no app launched.
  Notepad and VS Code (`code`) are on PATH. Chrome is **not** on PATH, so it should be found
  by the Start Menu `.lnk` search in `_find_start_menu_shortcut`. Ask the user to test
  "open chrome", or test carefully yourself.

## Phase 2 status (voice: built, awaiting the user's live test)
`interfaces/voice.py`, started with `main.py --voice` or option 2 in `jarvis.bat`. English only
(the user chose this). It uses the openWakeWord "hey_jarvis" model (onnx), faster-whisper `base.en`
on the CPU, and edge-tts `en-GB-RyanNeural` played with playsound3. The speech threshold adapts:
it calibrates the noise floor at start-up and tracks it while idle, with threshold =
max(noise × 4, 150). The user's mic is very quiet (noise ≈ 10), so the 150 minimum is what
actually applies. On wake it plays a cached, silence-trimmed "Yes, sir?" WAV through `winsound`.
After the acknowledgement and after each reply it drains the mic buffer and resets the wake
word. If edge-tts fails, replies are shown as text with a single warning. Not yet verified: a
real spoken exchange. If speech is not detected, tune `MIN_SPEECH_RMS` first.

## Phase 3 status (conversation memory: done and tested)
`core/history.py` stores every exchange in SQLite (`data/history.db`: `exchanges` and
`summaries` tables). Each `Brain` has a session id. `Brain.close()` (called on /exit, Ctrl+C or
voice stop) and `Brain.reset()` summarise the session in 1-3 sentences, or store `''` when
the model replies SKIP for trivial sessions. Sessions that ended without a clean exit are
summarised on the next start-up. The last 5 summaries are injected into the system prompt.
The `recall_conversations` tool does semantic search: `gemini-embedding-001` at 768 dims,
normalised, with embeddings computed lazily at search time and a fallback to keyword
LIKE search. The CLI has a `/memory` command that shows facts and recent summaries.
Tested: summaries carry over between sessions, and the model calls `recall_conversations`
when the answer isn't in its prompt.

## Roadmap
- **Phase 2, voice (built; see above):** wake word ("Jarvis"), then speech-to-text, then `Brain.ask`, then
  text-to-speech in a calm British male voice. Add it as `interfaces/voice.py` and keep the
  text CLI working. Prefer free and local options (for example openWakeWord or Porcupine's
  free tier for the wake word; faster-whisper for STT; edge-tts with an en-GB voice, or
  Gemini TTS models, for TTS). Check current package names and versions before installing.
  **First ask the user whether JARVIS must understand only English or Hindi/Hinglish too**;
  this was asked but not yet answered, and it affects the choice of STT model.
- **Phase 3, better memory:** done (see above).
- **Phase 4, HUD:** done. `interfaces/hud/server.py` (FastAPI + uvicorn, bound to
  127.0.0.1:8765 only) serves `interfaces/hud/static/` (index.html, style.css, app.js; no
  frameworks). Endpoints: `GET /api/stats` (psutil), `GET /api/memory` (facts and summaries),
  and `WS /ws` (client sends `{text}`; server sends `thinking`, `tool`, `reply` and `error`
  events). A single shared `Brain` is serialised by an asyncio lock and closed on shutdown.
  The page has an animated arc reactor whose states are idle, thinking, speaking, listening
  and offline; it also has gauges, top processes, memory and an activity feed. Optional
  browser voice uses the Web Speech API (mic button and a "Voice" toggle, Chrome/Edge only).
  Start it with `main.py --hud` or option 3 in `jarvis.bat`. Tested: all endpoints, a
  websocket chat with a tool call, and screenshots at 1600 and 1366 px wide.
- **Phase 6 and PC powers:** done. `core/llm.py` now holds the single shared Gemini client
  and the model-fallback `generate()`, used by the brain, vision and embeddings. New skills:
  - `skills/pc.py`: volume (pycaw), brightness (screen-brightness-control), screenshots
    saved to `~/Pictures/JARVIS Screenshots`, `type_text` and `press_keys` (pyautogui, with a
    clipboard-paste fallback for non-ASCII text), and media keys.
  - `skills/files.py`: `find_files` searches Desktop, Documents, Downloads, Pictures, Music,
    Videos and OneDrive, with an 8 s cap and newest files first. `open_file` refuses
    executables and scripts.
  - `skills/reminders.py` and `core/reminders.py`: each reminder is a Windows scheduled task
    under `\JARVIS\`, registered through PowerShell `-EncodedCommand`, that runs `pythonw
    notify.py <id>`. That script shows a winotify toast, marks the reminder done in
    `data/reminders.json` and unregisters the task. Reminders fire even when JARVIS is closed.
  - `skills/vision.py`: `look_through_webcam` (OpenCV, local reference photos in `data/faces`
    for recognition through Gemini), `look_at_screen`, and `remember_face` / `forget_face`.
    The persona says to use the camera only when the user asks.
  Not tested live, on purpose: typing and keys into real windows, media keys, a real webcam
  photo sent to Gemini, and a real screen sent to Gemini. Capture worked locally, and Gemini
  vision was verified with a synthetic image.
- **Phone access, Option A (same Wi-Fi):** done. `main.py --hud --lan` (option 4 in `jarvis.bat`)
  binds to 0.0.0.0 and prints a terminal QR code with the LAN URL and the PIN.
  `interfaces/hud/auth.py` provides the PIN (`JARVIS_HUD_PIN` env var, or a random 6 digits
  stored in `data/hud_auth.json`), 30-day HttpOnly SameSite=strict session cookies, and a
  lockout after 5 wrong PINs in 5 minutes. Loopback clients skip the PIN. Every request
  checks the Host header against an allowlist (anti DNS-rebinding). The websocket and
  POST /login check the Origin (anti cross-site websocket hijacking). There is a PWA
  manifest and icons for "Add to Home screen". All 14 security checks passed. The user's
  Wi-Fi profile was **Public**; it must be **Private** and Python allowed through Windows
  Firewall. Browser mic input needs HTTPS, so on the phone use the keyboard's dictation key.
  User's plan next: an encrypted details vault, then Android phone control over ADB and form
  filling in phone apps. ADB is installed at `%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe`.
- **Android phone control:** built. The phone is a POCO C85 5G on Android 15 (HyperOS),
  paired over Wireless debugging. `core/adb.py` finds the phone and, if it isn't connected,
  rediscovers it through `adb mdns services` and reconnects (the port changes after a
  restart). It raises a friendly `PhoneError`, including when Xiaomi blocks INJECT_EVENTS.
  `skills/phone.py` has open_app (aliases, intent apps, package matching, then
  resolve-activity and `am start`), list_apps, read_screen (`uiautomator dump /dev/tty` →
  numbered elements, with clickable parents absorbing their child labels), look_at_screen
  (screencap → Gemini), tap / type / press / scroll by element number, and status.
  `MAX_TOOL_CALLS_PER_TURN` is 25. The persona has phone safety rules: no payments,
  passwords, OTPs or security settings, and confirm before send / post / submit / buy / delete.
  Tested on the real phone: opening apps, reading the screen, status, reconnect, and
  brain-driven commands. **Tap, type, press and scroll are blocked until the user enables
  "USB debugging (Security settings)"**, and the code reports this correctly. `phone_type` is
  ASCII-only (`adb input text`); ADBKeyboard would be needed for Unicode.
- **Vault and form filling:** done.
  - `core/vault.py` uses DPAPI through ctypes (CryptProtectData with entropy) to write
    `data/vault.bin`. It defines TEMPLATE fields, with IDs marked sensitive, plus
    `mask()` and `redact()`.
  - `core/confirm.py` is the human gate. Interfaces install the handler: a Confirm prompt
    in the CLI (it pauses the spinner), and an Allow/Deny `<dialog>` in the HUD, sent over
    the websocket as `confirm` / `confirm_reply` while a reader task keeps receiving. The
    HUD times out after 120 s and counts that as Deny. Voice mode has no handler, so it
    always denies.
  - Gated in code: `phone_tap` on RISKY labels (submit, send, pay, apply, delete...),
    `phone_fill_field` for sensitive keys, and `phone_look_at_screen` within 15 minutes
    after typing a sensitive value.
  - `phone_read_screen` redacts vault values into `[your <label>]`. `skills/details.py`
    has `vault_list_fields` (keys and labels only) and `vault_save_field`, which refuses ID
    keys. The vault manager CLI is `interfaces/vault_cli.py` (`main.py --vault`, option 5).
  - Tested: encryption round trip, redaction, all gates, the HUD Allow/Deny flow (4
    scenarios), and a real-AI rehearsal on a simulated job form that filled 7/7 fields,
    flagged the missing one and was blocked at Submit.
  - Not yet tested on the real phone, because taps are still blocked by the POCO security
    switch.
- **Cloud brain (Phase A of the "works with laptop off" plan):** code done and tested
  locally; the user still has to deploy it. The plan is A cloud brain → B laptop agent →
  C Kotlin Android app (Accessibility) → D phone vault and forms → E FCM push and assistant
  button → F job search.
  - `core/db.py` uses SQLite locally, or Postgres when `DATABASE_URL` is set (psycopg3).
    SQL is written with "?" placeholders. The tables are exchanges, summaries, facts and
    sessions. `memory.py` and `history.py` now go through it, and memory.json migrates
    automatically.
  - `config.now()` gives the user's timezone (`JARVIS_TIMEZONE`, default Asia/Kolkata).
  - `skills/__init__.py` exposes `cloud_tools()` and `local_tools()` with lazy imports, so
    the cloud never imports Windows libraries. `Brain(on_tool, tools, context)`.
  - The shared websocket logic is `interfaces/hud/session.serve_chat`, and the shared login
    page is `interfaces/hud/login.py`.
  - `cloud/server.py` requires `JARVIS_PASSWORD` (12 characters or more) and has a host
    allowlist (`RENDER_EXTERNAL_HOSTNAME`), an origin check, DB-backed sessions (sha256 of
    the token, Secure cookie), per-IP lockout plus a global lockout of 10 failures per
    15 minutes, a 1 s delay on wrong passwords, security headers and no /docs. In cloud
    mode the HUD hides the systems panel.
  - Deployment files are `render.yaml` (free plan, Singapore, healthCheck /healthz) and
    `requirements-cloud.txt`. The database is Neon free Postgres, because Render's free
    Postgres is deleted after 30 days.
  - Tested against local Postgres (pgserver): auth (13 checks), chat, and a hard-kill
    restart where facts and the summary persisted.
  - **Deployed and live** at https://jarvis-cloud-5azx.onrender.com from GitHub
    `GaneshPawar2004/jarvis`, branch main, through the Render Blueprint "jarvis". It is on
    the free plan and sleeps after about 15 minutes. The first deploy failed because
    `JARVIS_PASSWORD` was too short; the user fixed it.
  - External checks passed: health, redirect to login, 401/403 without a session, fake
    origin blocked, HTTP→HTTPS, and security headers.
  - In the laptop `.env`, the Neon URL is named `NEON_DB_URL`, not `DATABASE_URL`, so laptop
    JARVIS still uses local SQLite. Unifying memory is part of Phase B.
  - The laptop has two GitHub accounts. The push remote is
    `https://GaneshPawar2004@github.com/...`, and pushing to main auto-deploys.
- **Phase B, laptop agent:** done and tested end to end against a local cloud.
  - Pairing: `POST /api/pair {password, name}` returns a device token (sha256 stored in the
    `devices` table). The laptop keeps it in `data/cloud_device.bin`, DPAPI-encrypted.
    `main.py --pair` asks for the password with getpass and never stores it.
  - The agent is `interfaces/agent.py` (`main.py --agent`, option 6 in jarvis.bat;
    `--agent-install` and `--agent-uninstall` manage a Task Scheduler AtLogOn task under
    `\JARVIS\`). It connects to `wss://…/agent` with `Authorization: Bearer`, which browsers
    can't send. It sends `hello` with FunctionDeclarations for `local_tools() - cloud_tools()`,
    runs `call` messages in threads, and relays `confirm` to the cloud, where it goes to the
    chat UI. Logs go to `data/agent.log`, and it reconnects with backoff up to 60 s.
  - Cloud: `cloud/agents.py` (Agents registry and remote proxies). `Brain.set_tools(tools,
    context, handlers)` swaps tools when the laptop comes or goes, and `Brain.note()`
    injects a status notice. The persona has a "live status overrides earlier messages"
    line, which fixed the model believing the laptop was still offline.
    `/api/stats` returns `laptop_online`.
  - Shared memory: `config.DATABASE_URL` falls back to `NEON_DB_URL`, so laptop JARVIS now
    uses Neon. `main.py --migrate-memory` copied the old SQLite data (8 messages and 5
    summaries).
- **Phase C, JARVIS Android app:** built (`android/`, Kotlin, no AndroidX, OkHttp only; AGP
  8.7.3, Gradle 8.11.1 wrapper, Kotlin 2.1.0, compile/target SDK 35, minSdk 28). Build with
  `JAVA_HOME=C:\Program Files\Java\jdk-20` and `android\gradlew assembleDebug`; the APK is
  copied to `D:\jarvis\JARVIS.apk`, which is gitignored. Not yet installed on the phone,
  which wasn't nearby.
  - `CloudLink.kt` is one OkHttp websocket to `/agent` with `{"type":"hello","kind":"phone"}`.
    It carries chat (`chat` → `chat_reply`/`chat_error`), tool `call`s and `confirm`s.
  - Pairing is `POST /api/pair`; the token is AES-GCM-encrypted with an Android Keystore key
    (`Prefs.kt`).
  - `LinkService` is a foreground service (specialUse) that keeps the link alive while other
    apps are on screen.
  - `JarvisAccessibilityService` reads the screen as numbered elements and taps, types
    (`ACTION_SET_TEXT`, so Unicode works), presses keys, scrolls and opens apps (activity
    starts from the accessibility service context are background-launch exempt).
  - `PhoneTools.kt` has the same `phone_*` names as the laptop's ADB tools. There is no
    `look_at_screen` and no vault yet; the vault is Phase D.
  - `ConfirmCenter` shows a heads-up notification with Allow/Deny and a 120 s timeout. RISKY
    taps are gated locally, and server-relayed confirms use the same notification.
  - `MainActivity` handles pairing and the chat UI, `SpeechRecognizer` (en-IN), TTS
    (`Locale.UK`), and the ASSIST intent, so the app can be the default assistant.
  - Cloud: `cloud/agents.py` now supports several devices (laptop and phone), chat over the
    agent socket, and `Agent.request()` for calls and confirms. `_devices_changed` gives the
    phone app's `phone_*` tools priority and drops ALL of the laptop's `phone_*` tools while
    the app is connected. `_context()` describes the live devices. `/api/stats` has
    `phone_online`.
  - `core/llm.py`: when every model returns 429 (free tier is 15 RPM per model), it waits
    the advertised retry delay once (if 60 s or less), then raises `QuotaExhausted` with a
    friendly message.
  - Tested with a simulated app (same JSON as the Kotlin app) plus the real laptop agent:
    phone chat, phone-tool routing, laptop tools, and the Allow/Deny relay to the app.
- **Phase D, phone vault and forms:** built, and the app builds cleanly. Not yet installed:
  the phone wasn't reachable over ADB.
  - `Crypto.kt` holds the Keystore AES-GCM seal and unseal, using the same alias and format
    as before, so existing pairings still work.
  - `Vault.kt` stores sealed JSON in SharedPreferences "vault", with the same TEMPLATE keys
    as the laptop vault, plus `mask()` and `redact()`.
  - `PhoneTools` adds `vault_list_fields` (labels only), `phone_fill_field` (sensitive keys
    go through ConfirmCenter, and typing uses ACTION_SET_TEXT so Unicode works) and
    `vault_save_field` (refuses ID keys). `phone_read_screen` output is redacted with the
    vault values.
  - The MY DETAILS screen in MainActivity is gated by `KeyguardManager` device credential
    (fingerprint or PIN). It lists template and custom fields, masks IDs, and supports
    edit, clear and custom fields.
  - No cloud change was needed: the phone's tools come first in `_devices_changed`, so the
    phone's vault tools shadow the laptop's.
- **Talk from any screen:** done and confirmed working on the user's phone.
  - The floating 🎤 is a `TYPE_ACCESSIBILITY_OVERLAY` bubble drawn by the accessibility
    service. It is draggable, snaps to the edge, is toggled with `Prefs.floatingMic`, and
    hides while `PhoneTools.run` executes.
  - `TalkTileService` provides a Quick Settings tile.
  - `ListenActivity` is a translucent bottom panel with `taskAffinity=""`, so the current
    app stays on screen. It also handles the ASSIST intent. It uses `SpeechRecognizer` and
    falls back to the `RecognizerIntent` Google pop-up on errors.
  - `CloudLink` queues chats while reconnecting and shows replies as a HIGH notification
    when MainActivity isn't visible.
  - The phone's default recognizer is Google's TTS recognition service, and the Google app
    is installed.
- **Phase F, job hunting:** built. Tested in the cloud against a made-up sample resume; not
  yet tried by the user.
  - `core/resume.py`: Gemini reads the PDF (`Part.from_bytes` application/pdf, JSON mime) into
    a profile containing summary_for_jarvis, skills, experience, education,
    suggested_roles and so on. It is stored in the `resumes` table. `summary()` goes into
    the persona as "The user's resume, in brief", and `vault_suggestions()` maps fields to
    vault keys.
  - `POST /api/resume` takes raw PDF bytes and an X-Filename header, authenticated by a
    device Bearer token or a browser session. It returns summary, suggested_roles and
    vault_suggestions; the app lets the user tick which suggestions to save locally.
    Laptop: `main.py --resume file.pdf`.
  - `skills/jobs.py` (cloud tools): `get_resume_profile` (without email or phone),
    `find_jobs` (ddgs, past month, keeping only real posts: naukri `/job-listings-` and
    linkedin `/jobs/view/`), `shortlist_job`, `list_jobs` and `update_job_status`, stored in
    the `jobs` table.
  - Persona: rank by fit, apply only on request and one at a time using `phone_open_url`
    plus the vault, confirm before Submit, never mass-apply.
  - App: "📄 UPLOAD RESUME (PDF)" in MY DETAILS (ACTION_OPEN_DOCUMENT), the result dialog
    with vault checkboxes, and a new `phone_open_url` tool.
- **Brain step 1:** done.
  - The live conversation is saved in a `threads` table (`history.save_thread` /
    `load_thread`, Content `model_dump` JSON; thought signatures survive). The cloud brain
    uses thread "main" and saves after every ask, note and reset. The laptop's offline
    fallback uses "laptop-offline".
  - Laptop chat, voice and HUD use `core/remote.connect_brain()`. It returns `RemoteBrain`,
    a websocket to `/agent` with `kind:"client"` (chat only, no tools, gets a `welcome`
    with device status), which handles `tool`, `confirm` (answered by the local confirm
    handler) and `chat_reply`, and reconnects once if the server restarted. If the laptop
    isn't paired or the cloud is unreachable, it falls back to a local Brain.
  - Server: `Agents(on_reset)` handles `{"type":"reset"}` with `reset_done`. Clients don't
    change the brain's tools.
  - Tested: chat, a laptop tool through the agent, Allow on the laptop, persistence across a
    hard server restart, reset, offline fallback.
  - Next: Memory 2.0 (relevant-only retrieval, a memory writer that updates facts,
    pgvector, Memory screen).
- **Phase 5, home and devices:** smart lights and plugs, media control (ask what hardware the user owns).
- **Phase 6, vision:** webcam, face recognition and scene description (Gemini is multimodal).
- **Phase 7, autonomy:** reminders, scheduled briefings, multi-step tasks.

## Working rules
- Ask before anything risky or irreversible: shell commands that delete or modify files,
  sending messages or emails, purchases, or launching many apps. Any future tool that runs
  shell commands or deletes files must require user confirmation inside JARVIS itself.
- Never expose the API key. Never commit `.env` or `data/`.
- Install packages only into `.venv`, and add each new one to `requirements.txt`.
- Match the existing code style: small modules, type hints, short docstrings, little extra commenting.
- After each change, actually run it (for example a short script that calls `Brain().ask(...)`)
  and report honestly what passed, what failed and what you could not test.
- Explain progress to the user in simple language, and end each phase by telling them how
  to run the new feature and what comes next.

## Your first steps
1. Read every file listed above to confirm that the code matches this description.
2. Run a quick smoke test: `.venv\Scripts\python -c "from core.brain import Brain; print(Brain().ask('What time is it?'))"`.
3. Ask the user the English vs Hindi/Hinglish question, then start Phase 2 (voice).

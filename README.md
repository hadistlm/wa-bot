# wa-bot

A bot that answers WhatsApp messages for you. It watches one chat you choose, asks Gemini for a reply in your voice, and sends it.

> **Heads up:** WhatsApp can ban accounts that use automation. Test on a spare number first.

## What you need

- Python 3.11 or newer
- A [Gemini API key](https://aistudio.google.com/)
- WhatsApp on your phone

## Install

```bash
git clone https://github.com/hadistlm/wa-bot.git
cd wa-bot
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e .
playwright install chromium
cp .env.example .env.local
cp persona.example.md persona.md
```

All commands are listed in [Commands](#commands).

## Configure

Open `.env.local` and set at least these:

| Variable | Example | What it does |
|---|---|---|
| `GEMINI_API_KEY` | `AIza...` | Your Gemini key. Required. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Any Gemini model name. |
| `PERSONA_NAME` | `Budi` | Your name. Fills `{name}` in the persona. |
| `OWN_NAMES` | empty | The name WhatsApp shows on your own messages, if the bot misreads them as incoming. It learns the name by itself. |
| `ALLOWED_CHATS` | `Budi,+62 812 3456 7890,*Santoso*` | Who the bot answers. See below. |
| `CONTEXT_MESSAGES` | `5` | How many recent messages Gemini sees. |

More options, all optional:

| Variable | Default | What it does |
|---|---|---|
| `PERSONA_FILE` | `persona.md` | Markdown file with your persona. Wins over `PERSONA_PROMPT`. |
| `PERSONA_PROMPT` | empty | Short persona text, used when the file is missing. |
| `ALLOW_GROUPS` | `false` | Answer group chats too. |
| `MATCH_THRESHOLD` | `0.85` | How close a typo may be to match a name. |
| `POLL_INTERVAL` | `4` | Seconds between checks. |
| `REPLY_DELAY_MIN` / `REPLY_DELAY_MAX` | `2` / `6` | Random pause before sending. Halved for friend chats. |
| `QUIET_HOURS` | empty | Window with no replies, such as `23:00-07:00`. Messages that arrive meanwhile get answered once it ends. |
| `TYPING_CHAR_DELAY_MS` | `140` | Average pause per typed key, about 7 characters a second. WhatsApp shows "typing..." while the bot types. `0` pastes instantly. |
| `TYPING_JITTER` | `0.4` | How uneven the keys are. `0` is a fixed rhythm, `1` is very uneven. |
| `MAX_TYPING_SECONDS` | `20` | Upper limit for the keys of one reply. Long replies type faster to fit. |
| `AFK_CHANCE` | `0.1` | Chance per incoming message that the bot goes AFK. `0` turns it off. |
| `AFK_MIN_MINUTES` / `AFK_MAX_MINUTES` | `3` / `20` | How long an AFK spell lasts. |
| `AFK_ACKNOWLEDGE` | `false` | After a long spell, Gemini may add a short "sori baru bales". |
| `AFK_ACK_MIN_MINUTES` | `5` | Shortest spell that counts as long. |
| `SKIP_BACKLOG` | `true` | Do not answer messages that were waiting before the bot started. |
| `WATCH_MODE` | `list` | `list` stays on the chat list and opens allowed chats that need an answer. `open` answers the chat you opened. |
| `OPEN_DELAY_MIN` / `OPEN_DELAY_MAX` | `1` / `4` | Random pause before opening a chat from the list. |
| `REPLY_GAP_MIN` / `REPLY_GAP_MAX` | `15` / `45` | Pause between answers to different chats. |
| `HEARTBEAT_MINUTES` | `5` | Minutes between "still watching" lines in the terminal. `0` turns them off. |
| `CHROMIUM_SANDBOX` | `true` | Keep on. Off shows an "unsupported --no-sandbox" banner in the browser. |
| `HEADLESS` | `false` | Hide the browser window. A minimized window is safer than headless. |
| `SKIP_TRIVIAL` | `true` | Ignore bare "ok", "makasih", "👍". |
| `DEBOUNCE` | `true` | Wait one poll so a burst of messages gets one reply. |
| `MAX_REPLIES_PER_HOUR` | `20` | Reply cap per chat. |
| `GEMINI_TEMPERATURE` | `0.8` | Higher means more varied replies. |
| `DB_PATH` | `data/wabot.db` | SQLite file with chat history. |
| `PROFILE_DIR` | `data/profile` | Saved WhatsApp login. |
| `BROWSER_CHANNEL` | empty | Set to `chrome` to use installed Chrome. |

### Choose who the bot answers

`ALLOWED_CHATS` takes a comma-separated list. Each entry can be:

- A name: `Budi` matches "Budi Santoso". Case and accents do not matter.
- A phone number in any format: `+62 812-3456-7890`, `0812 3456 7890` and `6281234567890` all match the same contact.
- A pattern: `*Santoso*` matches any name containing "Santoso".
- A near miss: `Budy` still matches `Budi`.
- A relationship tag after the entry: `work`, `friend`, `lover` or `family`, for example `Budi:work` or `Sari:lover`. Gemini gets it as context for the tone. Without a tag, the bot infers work or friend from the chat.

An empty list means the bot answers nobody.

### Write your persona

Edit `persona.md`. It is plain Markdown, and `{name}` becomes your `PERSONA_NAME`.

```markdown
# Persona
You are {name}, a senior fullstack developer in Yogyakarta, Indonesia.

## Language
Reply in the language of the latest message: casual Indonesian by default,
professional English when the sender writes English.
```

The bundled `persona.example.md` already does this. Gemini detects the sender's language from the chat, so no extra setting exists.

## How the bot learns each chat

The bot stores messages in SQLite and builds a profile for every chat from them, with no extra Gemini calls:

- **Language, formality and message length** of the other person. Gemini receives a short note such as "work contact, mostly English, formal, they write about 12 words".
- **Your own messages.** The bot tells your hand-typed messages from its own replies, then shows Gemini your last four so it copies your voice. Type a few replies yourself in a new chat to teach it.
- **Goes AFK** now and then. On about 1 in 10 incoming messages the bot stays silent for 3 to 20 minutes, in every chat. The spell is saved in the database, so a restart does not end it early.
- **Skips** bare acknowledgements, waits for a burst of messages to finish, and stops at the hourly cap.

A new chat has no history, so the bot uses the plain persona until about 5 messages are stored. History only grows while the bot runs.

### What happens after an AFK spell

- **The bot answers on its next check.** There is no timer or special trigger. The first poll after the spell reads the chat and replies to whatever is waiting, using the last 5 messages. If the sender wrote several messages meanwhile, they get one reply.
- **No back-to-back spells.** The first reply after a spell never rolls for another one.
- **A late reply can mention the delay.** With `AFK_ACKNOWLEDGE=true` and a spell of at least `AFK_ACK_MIN_MINUTES`, Gemini may add a short phrase such as "sori baru bales" in the sender's language.
- **If you answer by hand first,** the bot sees your message and stays quiet.
- **If the sender never writes again,** the bot answers once after the spell, then sends nothing more. It never follows up or nudges.
- **The chat must be in the visible list.** WhatsApp only renders the rows near the top. A waiting chat that has scrolled out of view cannot be opened, and the bot logs a warning.
- **Restarts skip old messages.** With `SKIP_BACKLOG=true`, a message that was already waiting when the bot started gets no reply. The exception is a message that caused a spell still running at restart, which the bot answers after the spell.

### Several messages at once

The bot handles one chat at a time. If two chats get a message within a few seconds:
- It answers the one that arrived first.
- It waits `REPLY_GAP_MIN` to `REPLY_GAP_MAX` seconds, then opens and answers the second one. The second chat stays unread until its turn.
- Every message rolls the AFK dice on its own turn. A spell pauses the whole queue, and the waiting chats are answered after it ends.
- A follow-up in the chat you just answered is not held back by the gap.

## Commands

Run these from the project folder with the virtual environment active (`source .venv/bin/activate`).

| Command | What it does | Gemini key |
|---|---|---|
| `python -m wabot --login` | Open WhatsApp Web and scan the QR code. Do this once. | no |
| `python -m wabot --list-chats` | Print the chats in the list, numbered, and say which ones `ALLOWED_CHATS` matches. | no |
| `python -m wabot --selftest` | Read-only check of the chat list. | no |
| `python -m wabot --selftest --chat "Name"` | Also open that chat and check messages, compose box and Esc. | no |
| `python -m wabot --dump-dom` | Save a redacted copy of the page structure to `data/dom/`. | no |
| `python -m wabot --send-test "Name"` | Send one message, `wabot send test, please ignore`, typed like a real reply, and check it appears. | no |
| `python -m wabot --dry-run` | Run the bot and print replies without sending. | yes |
| `python -m wabot` | Run the bot for real. Ctrl+C stops it. | yes |

Options:

| Option | Works with | What it does |
|---|---|---|
| `--chat "Name"` | `--selftest`, `--dump-dom` | Pick a chat by name. Case, accents and small typos are fine. |
| `--chat-index N` | `--selftest`, `--dump-dom` | Pick the Nth chat in the list instead (1 is the top row). |
| `--out DIR` | `--selftest`, `--dump-dom` | Folder for the page dumps. Default `data/dom`. |
| `--verbose` | the bot | Log the decision for every poll, not just changes. |

### First run, step by step

1. **Log in.** `python -m wabot --login`. A browser opens with a QR code. On your phone go to WhatsApp, Settings, Linked Devices, Link a Device, and scan it. The login stays saved in `data/profile/`.
2. **Check the page.** `python -m wabot --selftest --chat-index 1`. WhatsApp changes its page often, so this confirms the bot can read the chat list, open a chat, read messages and type. It never presses Enter. The report shows PASS, FAIL or INFO lines with counts only, no names or message text, so you can paste it when asking for help.
3. **Dry run.** Put a friend in `ALLOWED_CHATS`, then `python -m wabot --dry-run`. Replies print in the terminal and nothing is sent.
4. **Prove sending.** `python -m wabot --send-test "Name"` sends exactly one message, typed with your `TYPING_*` settings. To see the typing animation, watch the browser window. To see "typing..." on the other side, send it to a friend who knows, because your own chat never shows an indicator.
5. **Go live** with a low `MAX_REPLIES_PER_HOUR`: `python -m wabot`.

`--selftest --chat` types a short probe into the compose box and deletes it. Use your own chat for it, because a contact would briefly see "typing...".

`--selftest` and `--dump-dom` save a redacted copy of the page structure in `data/dom/`. Text, names, numbers, ids and image links are masked, so the files show only tags, classes and roles.

## Run it

Leave the browser window on the chat list. The bot opens a chat only when it is in `ALLOWED_CHATS` and has a message waiting, answers, then returns to the list. Chats outside the list are never opened, read or answered. To answer whichever chat you open yourself, set `WATCH_MODE=open`.

```mermaid
graph LR
    Q{Quiet hours?} -- yes --> Q
    Q -- no --> A[Read open chat]
    A --> B{In ALLOWED_CHATS?}
    B -- no --> Q
    B -- yes --> C[Save messages to SQLite]
    C --> D{Last message from them, unanswered?}
    D -- no --> Q
    D -- yes --> E[Ask Gemini with last 5 messages]
    E --> F[Type reply key by key, send]
    F --> Q
```

## Where your data lives

Everything the bot stores sits in one folder, `data/`, which git ignores.

```
data/
├── wabot.db     chat history, contact profiles, AFK state
├── profile/     saved WhatsApp login
└── dom/         redacted page dumps from --selftest and --dump-dom
```

Change the locations with `DB_PATH` and `PROFILE_DIR`. To read the history:

```bash
sqlite3 data/wabot.db "select sender, text from messages order by id desc limit 10"
```

Upgrading from an older version? Move the old files in: `mkdir -p data && mv .wa-profile data/profile && mv wabot.db* data/`, and update `DB_PATH` and `PROFILE_DIR` in `.env.local`.

## Lower the ban risk

WhatsApp can ban accounts that automate messages, and no setting removes that risk. These steps help:

- Answer only people who wrote to you first, and keep `ALLOWED_CHATS` short.
- Keep the bot on the chat list. It never opens chats outside the allowlist.
- Set `QUIET_HOURS` so the bot sleeps at night.
- Keep `AFK_CHANCE` above 0 so the bot sometimes goes away for a few minutes, like a person would.
- Keep the typing on (`TYPING_CHAR_DELAY_MS` above 0). Each reply waits a moment, types key by key at an uneven pace with small beats after spaces and punctuation, pauses, then presses Enter, so the other person sees "typing..." and the message does not land instantly.
- Lower `MAX_REPLIES_PER_HOUR` to 6 to 10 and raise `REPLY_DELAY_MAX` to about 40.
- Use an established number, not a new SIM.
- Set `BROWSER_CHANNEL=chrome` and run the bot from the same machine each time.
- Never use it for bulk or marketing messages.

## Troubleshooting

- **The bot says "running" but ignores a chat that has unread messages.** Read the lines under "chats it will act on or is holding back" at startup, and the lines that follow. Each unread chat gets one line saying why. The usual reasons:
  - `not in ALLOWED_CHATS`: add the chat, or check the spelling with `--list-chats`.
  - `was waiting before start ... (SKIP_BACKLOG)`: the message came before the bot started. A new message wakes it, or set `SKIP_BACKLOG=false`.
  - `waiting one poll`, `waiting for the reply gap`, `cooling down`, `paused until ... (AFK spell)`: temporary waits, no action needed.
  Run with `--verbose` to see every poll.

- **"session expired":** run `python -m wabot --login` again.
- **Gemini error "fatal":** check `GEMINI_API_KEY` and `GEMINI_MODEL`.
- **WhatsApp says the browser is unsupported:** set `BROWSER_CHANNEL=chrome`.
- **The bot never opens a chat:** the title in the chat list must match an `ALLOWED_CHATS` entry, and the row must be unread or have a waiting message. A group stays unanswered unless `ALLOW_GROUPS=true`.
- **The bot answers its own messages:** it cannot tell your messages from theirs. Run `--selftest --chat-index N` and check the "own messages recognised" line, then set `OWN_NAMES` to the name WhatsApp shows on your messages.
- **Nothing is read from the chat:** WhatsApp changed its page. Run `python -m wabot --selftest --chat "Name"` to see which check fails, then update `src/wabot/whatsapp/selectors.py`.

## Keep private

Never share `.env.local`, `persona.md` or anything in `data/`. They hold your key, your login, your chats and a profile of each contact. WhatsApp also logs out linked devices if your phone stays offline for about 14 days.

## Develop

```bash
pip install -e ".[dev]"
pytest && ruff check . && mypy src
```

The tests use made-up names. `tests/test_my_config.py` also checks your own `.env.local` (allowlist not empty, no mistyped tags such as `Sari:lovr`) and is skipped when that file is missing.

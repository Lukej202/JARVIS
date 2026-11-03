# JARVIS: approved Chrome tab reading

This package uses the **uploaded 706-line `jarvis_core.py`** and the tested **v3 `jarvis_browser.py`**. It keeps terminal/GUI/voice, Ollama, memory, and existing approvals. The new action is `read_chrome_tab`.

## Important behavior
- Chrome must already be running in the dedicated `JARVIS-Chrome` debugging profile on Windows, with its debugging port listening only on localhost 9222.
- Only explicitly named **public HTTP(S) tabs** already open in that profile can be read. It **does not** inspect your regular Chrome sessions.
- A read must be **approved** in the GUI approval panel or terminal before any Chrome page content is retrieved. The browser reader does not click, navigate, fill forms, or log in.
- Upon approval the reader extracts up to 12,000 characters of rendered page text and sends at most 11,000 characters to local Qwen3 for summarization. The resulting summary is recorded as an action update in shared chat history.
- If a page only exposes a cookie banner and navigation links, the summary should say that the content is incomplete.
- The original HTTP `fetch_web_page()` and Chrome-launching `search_web()` remain unchanged.

## Install safely (WSL)

Stop Flask (`Ctrl+C`) before replacing code. Review your Git status and commit existing changes first if needed. In **WSL Ubuntu** run:

```bash
cd ~/JARVIS
git status
cp jarvis_core.py ~/jarvis_core_before_chrome.py
# Download the ZIP into your Windows Downloads folder first.
unzip -o /mnt/c/Users/lukej/Downloads/JARVIS_Chrome_Integration.zip -d ~/JARVIS
source .venv/bin/activate
python -m py_compile jarvis_core.py jarvis_browser.py integrated_voice_app.py
python integrated_voice_app.py
```

The ZIP contains only `jarvis_core.py`, `jarvis_browser.py`, and this README. It does not touch `.env`, the SQLite databases, or `workspace/`. The backup is in your WSL home directory (outside the Git repository). If you already made changes to `jarvis_core.py` since your most recent upload, review the ZIP file diff before replacing it.

## Test

In the JARVIS Chrome debugging window, open `https://www.python.org/about/`.
In the JARVIS GUI chat, enter:

`Jarvis, read this Chrome tab https://www.python.org/about/ and summarize what it says.`

This should **queue an approval**. Review the exact URL, approve it, and read the action update in the conversation panel. To test the previously blocked page, first open `https://kascope.com/industries/industrial/` in the same dedicated Chrome window and repeat the request with that URL. Do not use your personal Chrome window.

If the page redirects, use the final exact URL shown by Chrome. If the summarizer cannot see a page's main text (e.g., cookies/JS gating), it should report incomplete evidence.

## Git

Check branch and `git status`, review the diff, and stage only the intended files:

```bash
git add jarvis_core.py jarvis_browser.py
git diff --cached --check
git diff --cached --stat
```

Then commit and push on your feature branch. Do not stage your `.env`, `.db`, lock files or browser profile.

## Rollback

Stop Flask and run `cp ~/jarvis_core_before_chrome.py ~/JARVIS/jarvis_core.py`; then restart Flask.

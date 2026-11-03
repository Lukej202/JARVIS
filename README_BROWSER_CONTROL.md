# JARVIS — Milestone 13: Browser-only public research

## What this first version does

- Uses your **existing, separately launched `JARVIS-Chrome` profile** and the Windows localhost Chrome debugging service on `127.0.0.1:9222`.
- Creates **one new research tab** in that profile for each authorized task; does not manipulate your personal Chrome profile or your desktop mouse/keyboard.
- Searches Google, finds public result links, navigates up to **three** of them automatically, extracts visible page text, and asks your **local Qwen3 model** to summarize the actual evidence with URLs.
- Uses **one existing JARVIS approval card per research task**, not one per navigation.
- Adds a **STOP BROWSING** button in the GUI that requests cancellation between browser steps. A currently running PowerShell call may take up to roughly 30 seconds to finish before the stop takes effect.
- Retains Kokoro `bm_lewis`, Whisper, the GUI, and the existing tools.

**Restrictions:** No arbitrary mouse/keyboard, model-authored JavaScript, form filling, login, purchases, submissions or intentional downloads. Only public HTTP(S) destinations on ports 80/443 are allowed. Public webpage text is treated as untrusted and cannot instruct the agent to take actions. This is **not** a complete security sandbox: Chrome DevTools has high privileges in its dedicated browser profile and pages themselves can run JavaScript or initiate redirects. Do **not** sign in to personal accounts in `JARVIS-Chrome`; do not expose port 9222 to your network. The reader uses Chrome DevTools directly because the Windows PowerShell bridge has already worked on your machine. Playwright can replace this bridge later.

## Step 1 — Create feature branch

```bash
cd ~/JARVIS
git status -sb
# Only when your working tree is clean:
git switch -c feature/browser-control
```

If the branch exists, switch to it with `git switch feature/browser-control` instead. Commit any prior voice changes first.

## Step 2 — Install the new files (without overwriting working code)

Download `JARVIS_Browser_Control_M13.zip` into your Windows Downloads folder. Stop your Flask server with Ctrl+C. Then:

```bash
cd ~/JARVIS
unzip -o /mnt/c/Users/lukej/Downloads/JARVIS_Browser_Control_M13.zip -d ~/JARVIS
python install_browser_control.py
```

The installer checks for known code insertion points, validates the resulting Python, and **creates backups outside** your Git repository in `~/JARVIS-backup-browser-M13-<timestamp>/`. It patches only `jarvis_core.py`, `integrated_voice_app.py`, and `static/app.js` in place. It does not touch the TTS worker, model files, database, `.env`, or templates.

If it reports **“expected exactly one known insertion point”**, stop and show the error; **do not** replace your core with an older copy. You may have a slightly different version that needs a targeted patch.

## Step 3 — Check syntax and Chrome

```bash
source .venv/bin/activate
python -m py_compile jarvis_core.py integrated_voice_app.py jarvis_browser_control.py
node --check static/app.js  # optional; skip if Node.js isn't installed
powershell.exe -NoProfile -Command '(Invoke-RestMethod -Uri "http://127.0.0.1:9222/json/version").Browser'
```

Keep the separate JARVIS Chrome window running; launch it in Windows PowerShell if needed:

```powershell
$chrome = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
& $chrome --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --user-data-dir="$env:TEMP\JARVIS-Chrome" 'https://www.python.org/about/'
```

Do **not** open remote debugging on your regular Chrome profile.

## Step 4 — Test Chrome automation BEFORE enabling the AI

From WSL, run:

```bash
python jarvis_browser_control.py "Python programming documentation"
```

Chrome should create a **new** tab, open a Google search, navigate a couple of public result pages, and print a JSON report containing titles, source URLs and previews. If Google serves a consent/verification page, the report will say it could not find suitable result links; this is a website limitation, not permission to bypass anti-bot protections. If a site blocks access, it is skipped and reported, not invented. Your normal Chrome remains untouched.

## Step 5 — Test JARVIS end to end

```bash
python integrated_voice_app.py
```

Open `http://127.0.0.1:5000/` in your normal browser; refresh with `Ctrl+Shift+R`.

Try **“Jarvis, research Python programming documentation”**. The response should first request **one approval**. Approve the browser-research card. Watch the separate `JARVIS-Chrome` research tab move between the search results and public pages. You should get a sourced summary, not a claim about unverifiable pages. Try the **STOP BROWSING** button during a later task to request cancellation.

To avoid waiting for a Qwen decision, the `run_turn` path routes explicit “Jarvis, research …”, “search the web for …”, and “look online for …” commands directly to the approval queue.

## Troubleshooting

- **No Chrome connection:** Test Chrome from Windows PowerShell with `(Invoke-RestMethod http://127.0.0.1:9222/json/version).Browser`. The separate debugging window must be open.
- **No Google results:** Open the separate JARVIS Chrome tab manually and see whether Google displays a challenge or consent banner. The automation doesn't bypass those checks.
- **Approval takes time:** The approved action performs browsing and then local Qwen summarization; the HTTP approval request stays open until it finishes. The Stop button uses a separate endpoint to allow cancellation between steps.
- **Missing STOP button:** Hard-refresh the GUI (`Ctrl+Shift+R`) and check the console for JavaScript errors.
- **Source content incomplete:** Some sites require JavaScript, consent or a login; JARVIS must report limited evidence rather than hallucinate.
- **Restore backup:** If anything breaks, stop Flask; copy the corresponding backed-up `jarvis_core.py`, `integrated_voice_app.py`, and `static/app.js` from the directory printed by the installer to their original locations.

## Git commit after successful end-to-end test

```bash
git status -sb
git add jarvis_core.py jarvis_browser_control.py integrated_voice_app.py static/app.js install_browser_control.py README_BROWSER_CONTROL.md
git diff --cached --check
git diff --cached --stat
# Review to ensure no .env, SQLite DBs, or model binaries are staged.
git commit -m "Add supervised browser-only Chrome research"
git push -u origin feature/browser-control
```

**Note:** This is the first *bounded, read-only autonomous research* version, not unrestricted control of arbitrary websites. Once it's tested, we can add public-link clicking, scrolling, and richer tab management with the same permission boundaries.

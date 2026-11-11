# JARVIS → Your Regular Chrome (Milestone 14, extension bridge v0.2)

**Purpose:** An approved research command in the JARVIS dashboard opens new tabs in your existing Chrome profile through the JARVIS Research Tabs extension. It returns text and source URLs to Qwen3.5 (or the model selected by `JARVIS_MODEL`). No separate remote-debugging Chrome window is needed.

## Install (WSL)

1. **Back up/commit** your working code, then stop Flask (`Ctrl+C`).
2. Extract this ZIP into `/tmp/jarvis-bridge-v02`.
3. Run the installer, giving it the *existing unpacked extension folder*:

   ```bash
   cd ~/JARVIS
   python /tmp/jarvis-bridge-v02/install_chrome_bridge.py \
     --extension-dir /mnt/c/Users/lukej/Documents/JARVIS-Chrome-Extension
   ```

   The installer verifies the SHA256 hashes of the three uploaded source files **before changing anything**. If it reports a mismatch, stop and compare the files—**do not force overwrite**. Backups are saved outside your Git repo.

4. Start the GUI with your selected model:

   ```bash
   JARVIS_MODEL=qwen3.5:4b python integrated_voice_app.py
   ```

5. In a *second WSL terminal*, reveal the local private pairing key (do not share it publicly):

   ```bash
   cd ~/JARVIS
   python jarvis_extension_bridge.py pair
   ```

6. In regular Chrome, open `chrome://extensions`, **Reload** the `JARVIS Research Tabs` extension, and accept the updated site-permissions warning. Open its toolbar popup, paste the key, and select **CONNECT TO LOCAL JARVIS**. It should say `Bridge: connected to local JARVIS`.
7. Test in the JARVIS dashboard: **"Jarvis, research Python documentation."** Approve once in the dashboard. JARVIS should open new tabs beside your existing tabs, read up to 3 *public* pages, show sourced results, and speak through Kokoro Lewis.

## Security and boundaries

- The manifest requests `https://*/*` to read arbitrary public research sites, plus local HTTP access to `127.0.0.1`. **Chrome's actual host permission is broad**. The extension's code restricts DOM reading to tabs created by itself. This is a software rule, not an OS/browser isolation guarantee.
- Do not use the research-created tabs to open signed-in banking, email, account, medical, or confidential pages. The extension has a denylist of sensitive domains and checks for login forms, but no denylist is exhaustive.
- The extension uses a persistent random pairing key in `.jarvis_extension_key`, which must **never be committed**. Only the user should paste it into the extension popup. The key is held in extension-local storage.
- The Flask listener remains bound to `127.0.0.1:5000`. Never expose it directly to other machines/the Internet. No arbitrary JavaScript from Qwen is executed; the extension uses fixed DOM extraction functions.
- Approved research can automatically search, create tabs, navigate to public results, and extract page text. It **cannot** submit forms, log in, purchase items, or use system mouse/keyboard. The Stop Browsing button sets a cancellation flag checked between page operations.
- Search queries go to Google/Bing; public webpage text goes only to your local Flask process and Ollama (unless you explicitly configure another model endpoint).
- Sites can show bot checks, blocked articles, consent screens, and noisy excerpts. JARVIS should acknowledge missing evidence, not invent facts.

## Offline checks and troubleshooting

```bash
cd ~/JARVIS
python -m py_compile jarvis_core.py integrated_voice_app.py jarvis_extension_bridge.py
python test_extension_bridge.py
node --check /mnt/c/Users/lukej/Documents/JARVIS-Chrome-Extension/background.js  # optional
```

- `Bridge: not paired`: start Flask, check its local address, run `python jarvis_extension_bridge.py pair`, paste the key and connect.
- `Bridge: Flask offline`: verify WSL port 5000 is forwarded to Windows `http://127.0.0.1:5000` (open JARVIS dashboard from the same Chrome).
- `Extension not connected`: open popup; the alarm refresh interval may take up to ~30 seconds after a suspended service worker resumes.
- `No search results extracted`: Google may display a consent screen or changed markup. This version tries Bing as fallback. Inspect the JARVIS-created search tab, never your personal tabs.
- If Flask or Chrome closes mid-task, pending approval may fail or time out; retry after reconnecting.
- To roll back, restore the installer backups (path printed on installation); reload extension and restart Flask.

## What changed

- `jarvis_core.py`: approved `browser_research` goes through `jarvis_extension_bridge.enqueue_research()` rather than the old Chrome remote-debugging controller; source list attached to every successful report.
- `integrated_voice_app.py`: authenticated `/extension/{health,next,cancel, result}` routes and Stop Browsing rerouted to bridge.
- `jarvis_extension_bridge.py`: local pairing-key authentication, task queue, cancellation and bounded results.
- `extension/`: refreshed manifest, background worker, popup pairing UI. Manual open/read buttons continue to work.
- `static/app.js`: only small status-label refinements; Kokoro/voice and approval flows remain intact.

**Not yet live-tested on your Windows Chrome**. Offline syntax and bridge state tests were run; installation and actual website navigation need your confirmation.

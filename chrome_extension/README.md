# JARVIS Chrome Extension — V1 (browser-only prototype)

This is a safe, incremental prototype to prove JARVIS can **open and read its own research tabs in your everyday Chrome window**. It does not yet connect to the Flask agent. Do not treat the popup's reading as an autonomous research report until the bridge is added.

## Install in regular Chrome

1. Extract the ZIP to a permanent folder on your **Windows** drive, such as `C:\Users\lukej\Documents\JARVIS-Chrome-Extension`.
2. Open `chrome://extensions` in the **regular Chrome** window containing ChatGPT.
3. Turn on **Developer mode** (upper right).
4. Click **Load unpacked** and select the folder containing `manifest.json`.
5. Pin **JARVIS Research Tabs** using Chrome's extensions/puzzle icon.

## Test

1. Click the extension icon. Type `affordable FPGA development boards VHDL Verilog` and click **OPEN RESEARCH TAB**.
2. A Google search should open **in your regular Chrome window** as a new tab.
3. Click the JARVIS extension icon again, then **READ JARVIS TAB**.
4. Chrome may ask for permission to read Google; approve if comfortable. It requests website permissions on demand, not global access up front.
5. The popup should show a page title, URL, visible text, and some links.
6. Click one of the listed links. It should open in another JARVIS-created tab, beside the tabs you already had. Reopen the popup and click **READ JARVIS TAB** again to read it (and grant that website permission if prompted).
7. **CLOSE JARVIS TABS** closes only tabs created through this extension; it cannot close your ChatGPT tab.

## Security and limits

- No desktop mouse or keyboard permission; Chrome DevTools port 9222 is **not** needed and should remain disabled for your regular Chrome profile.
- It does not read arbitrary existing tabs. A background script checks tab IDs against a list of tabs created by this extension before reading or closing them.
- Website read access is requested per origin using `optional_host_permissions`. Chrome's permissions are domain-scoped rather than tab-scoped; our code additionally enforces tab ownership. Don't mistake the code-level boundary for an OS-level sandbox.
- It opens Google search pages, lets you open collected HTTP(S) links and extracts readable text. It does **not** post forms, log in, download files, buy anything, or programmatically click through sites.
- Do not use JARVIS-created tabs for private email, banking, or password entry. Avoid granting permission on sensitive account websites.
- Some websites are inaccessible to extensions, render little readable text, or show bot checks/paywalls. This tool cannot bypass them.
- It rejects common private/localhost URLs and non-web schemes, but this is defense-in-depth and **not** a complete URL/IP security sandbox.
- Keep the extension source folder intact. If you edit it, reload the extension from `chrome://extensions`.

## Next phase

Once the test works, add a narrow, authenticated localhost bridge between the extension and `jarvis_core.py`/Flask. That will let the Qwen3.5 agent request page reads and get verified excerpts, while respecting user-approved tasks and stop controls. The browser-only prototype is intentionally separate so it doesn't break existing Kokoro, Whisper, tools, or SQLite memory.

# Project JARVIS — Milestone 14: User-Approved Memory (Stage 1)

This module adds a **separate, local SQLite database** for facts and preferences the user has specifically asked JARVIS to retain. It does **not** automatically turn ChatGPT-style conversations, Qwen's generated answers, webpages, research snippets, or tool outputs into trusted facts.

## Why this matters

Earlier, JARVIS repeatedly claimed it was 2024 because its own mistaken chat responses were included in the conversation history. User-approved memory is stored separately, and JARVIS has a read-only memory lookup tool. It is **not** a fact-checking system: the label `user_approved` means the user authorized saving that statement, **not** that it has been independently proven true.

## Setup

1. From a clean, up-to-date `main` branch, create `feature/verified-memory`.
2. Download the package and extract it outside the repository (e.g., `/tmp/jarvis-m14`).
3. Run `python install_verified_memory.py --project ~/JARVIS` from inside the extracted folder. The installer checks code anchors and saves a dated backup to `~/JARVIS-memory-backups/`.
4. Run `python -m py_compile ~/JARVIS/jarvis_core.py ~/JARVIS/jarvis_verified_memory.py` and `python test_verified_memory.py` from the extracted folder.
5. Restart Flask with your working Qwen 3.5 launch command.

No Flask, GUI JavaScript, TTS, browser bridge, extension, chat-history DB, or action-history DB changes are required.

## In the JARVIS GUI

- **Propose a save:** `Jarvis, remember that I prefer FPGA development projects using VHDL.`
  - JARVIS requests approval; the database is **not** written until you approve in the dashboard.
- **List:** `Jarvis, what do you remember about me?` or `/memories`.
- **Find relevant saved facts:** Ordinary chat has a read-only `recall_user_memory` tool. Tool use is model-dependent in this first stage; `/memories` is deterministic.
- **Propose a removal:** `Jarvis, forget memory 0123abcd` using the exact ID from `/memories`.
  - Removal also requires approval. It deletes that record from **active verified memory**.

## Privacy and limits

- Database: `~/JARVIS/jarvis_verified_memory.db`. The `.gitignore` rule excludes `jarvis_verified_memory.db*` (including SQLite journal files) from Git.
- Locally stored on disk, not encrypted at rest. **Don't save passwords, API keys, private account tokens, or other secrets.**
- Maximum 200 facts, 320 characters each; no automatic imports from the old chat history.
- Removing a memory does **not** erase copies that may still appear in `jarvis_memory.db`, `jarvis_actions.db`, prior backups, screenshots, or terminal logs. This stage does not claim full erasure.
- The memory module itself does not access the browser or contact outside services. The Qwen model remains local when configured through your existing Ollama setup.

## Scope of Stage 1

This release makes approved saves and explicit recall reliable. **It does not yet guarantee that the LLM will proactively retrieve the right memory before every ordinary answer.** Stage 2 can add relevant-memory context injection and a review/edit dashboard once this basic storage and approval behavior works.

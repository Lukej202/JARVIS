"""Terminal entrypoint for the shared local JARVIS brain."""
from jarvis_core import WORKSPACE, decide_action, pending_actions, run_turn


def main() -> None:
    print("JARVIS: Online (local Ollama, shared voice + text memory).")
    print(f"JARVIS: WSL workspace: {WORKSPACE}")
    print("JARVIS: /pending, /approve ID, /deny ID, exit")
    while True:
        try:
            message = input("You: ").strip()
            if message.lower() in {"exit", "quit"}:
                print("JARVIS: Shutting down.")
                break
            if not message:
                continue
            if message == "/pending":
                actions = pending_actions()
                if not actions:
                    print("JARVIS: No pending approvals.")
                for item in actions:
                    print(f"  {item['id']} — {item['summary']}")
                    if item["content"]:
                        print("  Proposed content:\n", item["content"])
            elif message.startswith("/approve ") or message.startswith("/deny "):
                verb, _, action_id = message.partition(" ")
                print("JARVIS:", decide_action(action_id.strip(), verb == "/approve"))
            else:
                print("JARVIS:", run_turn(message))
                actions = pending_actions()
                if actions:
                    print("JARVIS: Pending approvals (use /pending to review):")
                    for item in actions:
                        print(f"  {item['id']} — {item['summary']}")
        except (KeyboardInterrupt, EOFError):
            print("\nJARVIS: Shutting down.")
            break
        except Exception as exc:
            print(f"JARVIS: Error: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()

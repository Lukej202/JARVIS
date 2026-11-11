
import os
import asyncio
import discord
from dotenv import load_dotenv
from jarvis_core import run_turn, pending_actions, decide_action, recent_actions

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OWNER_ID = int(os.environ["DISCORD_OWNER_ID"])

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"JARVIS connected as {client.user}")


@client.event
async def on_message(message):
    if message.author.bot:
        return

    if message.author.id != OWNER_ID:
        return

    user_input = message.content.strip()

    if not user_input:
        return

    # Connection test
    if user_input.lower() == "jarvis ping":
        await message.channel.send("Online and operational, sir.")
        return

    # View pending approval requests (these are never executed automatically).
    if user_input.lower() == "/pending":
        try:
            actions = await asyncio.to_thread(pending_actions)
            if not actions:
                await message.channel.send("No pending approvals.")
            else:
                for action in actions:
                    await message.channel.send(
                        f"Pending `{action['id']}`: {str(action['summary'])[:1500]}\n"
                        f"To see proposed content, send `/review {action['id']}`."
                    )
        except Exception as exc:
            print(f"Approval error: {type(exc).__name__}: {exc}")
            await message.channel.send("Unable to retrieve pending approvals.")
        return

    # Display a proposed file/change before the user chooses whether to approve it.
    if user_input.lower().startswith("/review "):
        action_id = user_input.split(maxsplit=1)[1].strip()
        actions = await asyncio.to_thread(pending_actions)
        action = next((a for a in actions if str(a['id']) == action_id), None)
        if action is None:
            await message.channel.send("Unknown or non-pending action ID.")
            return
        content = str(action.get('content') or '(No text content to review)')
        await message.channel.send(
            f"Review `{action_id}`: {str(action['summary'])[:400]}\n"
            "Only approve if you recognize and trust the proposed action."
        )
        # Avoid Discord's 2,000-character message limit.
        for i in range(0, min(len(content), 10000), 1800):
            await message.channel.send(f"```text\n{content[i:i+1800].replace('```', '~~~')}\n```")
        if len(content) > 10000:
            await message.channel.send("Preview truncated. Review the full action in the local dashboard.")
        return

    # Explicit approval still required for overwrites and other protected actions.
    if user_input.lower().startswith(("/approve ", "/deny ")):
        command, action_id = user_input.split(maxsplit=1)
        action_id = action_id.strip()
        try:
            actions = await asyncio.to_thread(pending_actions)
            action = next((a for a in actions if str(a['id']) == action_id), None)
            if action is None:
                await message.channel.send("Unknown or non-pending action ID.")
                return
            result = await asyncio.to_thread(decide_action, action_id, command.lower() == "/approve")
            await message.channel.send(str(result)[:1900])
        except Exception as exc:
            print(f"Approval error: {type(exc).__name__}: {exc}")
            await message.channel.send("Could not process approval. See bot terminal for details.")
        return

    async with message.channel.typing():
        try:
            existing_ids = {a['id'] for a in await asyncio.to_thread(pending_actions)}
            before_actions = {a['id'] for a in await asyncio.to_thread(recent_actions, 30)}
            response = await asyncio.to_thread(run_turn, user_input)
            response = str(response)

            for i in range(0, len(response), 1900):
                await message.channel.send(response[i:i + 1900])

            # Report verified file operations from the backend's action log.
            completed = [a for a in await asyncio.to_thread(recent_actions, 30)
                         if a['id'] not in before_actions
                         and a['status'] == 'completed'
                         and a['kind'] in {'create_file', 'create_folder'}]
            for action in reversed(completed):
                await message.channel.send(f"Verified: {str(action['result'])[:1750]}")

            new_actions = [a for a in await asyncio.to_thread(pending_actions)
                           if a['id'] not in existing_ids]
            for action in new_actions:
                # The primary response already includes this ID for /task.
                if f"{action['id']}" in response:
                    continue
                await message.channel.send(
                    f"Action waiting for approval: `{action['id']}`. "
                    f"Use `/review {action['id']}` for details."
                )

        except Exception as exc:
            print(f"JARVIS error: {type(exc).__name__}: {exc}")
            await message.channel.send(
                "I encountered an error processing that request."
            )


if not TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN is missing from .env")

client.run(TOKEN)

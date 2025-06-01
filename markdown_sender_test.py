# simple_markdown_sender.py
import asyncio
from telegram import Bot
from config import Config # Your existing config

async def main():
    cfg = Config()
    bot = Bot(token=cfg.TELEGRAM_TOKEN)
    chat_id = 5835173900 # Replace with your actual chat ID

    # Paste the problematic Markdown string here
    problematic_md_message = """🚨 *Price Alert Triggered* 🚨

🔔 *Label*: _SOL high_
🪙 *Token*: *Solana \\(SOL\\)*
📈 *Current Price*: `$170.1234`
🎯 *Condition*: Above `$180.00`

_This alert may have been automatically deactivated\\._""" # Example

    try:
        await bot.send_message(chat_id, problematic_md_message, parse_mode="MarkdownV2")
        print("Message sent successfully with MarkdownV2!")
    except Exception as e:
        print(f"Error sending MarkdownV2: {e}")
        # Try plain text
        try:
            await bot.send_message(chat_id, problematic_md_message, parse_mode=None)
            print("Message sent successfully as PLAIN TEXT.")
        except Exception as e2:
            print(f"Error sending plain text either: {e2}")

if __name__ == "__main__":
    asyncio.run(main())
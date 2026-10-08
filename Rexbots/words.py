# Rexbots
# Don't Remove Credit
# Telegram Channel @RexBots_Official

from pyrogram import Client, filters
from pyrogram.types import Message
from database.db import db

@Client.on_message(filters.command("set_del_word") & filters.private)
async def set_del_word(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("**Usage:** `/set_del_word word1 word2 ...`\n\nये शब्द कैप्शन और फाइल के नाम से अपने आप हट जाएंगे।")
    
    words = message.command[1:]
    try:
        await db.set_delete_words(message.from_user.id, words)
        await message.reply_text(f"**सफलतापूर्वक डिलीट लिस्ट में जोड़ा गया:** `{', '.join(words)}`")
    except Exception as e:
        await message.reply_text(f"**Error:** `{e}`")

@Client.on_message(filters.command("rem_del_word") & filters.private)
async def rem_del_word(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("**Usage:** `/rem_del_word word1 word2 ...`")
    
    words = message.command[1:]
    try:
        await db.remove_delete_words(message.from_user.id, words)
        await message.reply_text(f"**डिलीट लिस्ट से हटाया गया:** `{', '.join(words)}`")
    except Exception as e:
        await message.reply_text(f"**Error:** `{e}`")

# Rexbots
# Don't Remove Credit
# Telegram Channel @RexBots_Official

@Client.on_message(filters.command("set_repl_word") & filters.private)
async def set_repl_word(client: Client, message: Message):
    # Syntax: /set_repl_word target replacement
    if len(message.command) < 3:
        return await message.reply_text("**Usage:** `/set_repl_word पुराना_शब्द नया_शब्द`\n\nExample: `/set_repl_word @OldChannel @NewChannel`")
    
    target = message.command[1]
    replacement = message.command[2]
    
    try:
        await db.set_replace_words(message.from_user.id, {target: replacement})
        await message.reply_text(f"**सफलतापूर्वक रिप्लेसमेंट सेट हुआ:**\n`{target}` ➔ `{replacement}`")
    except Exception as e:
        await message.reply_text(f"**Database Error:** `{e}`")

@Client.on_message(filters.command("rem_repl_word") & filters.private)
async def rem_repl_word(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("**Usage:** `/rem_repl_word target`")
    
    target = message.command[1]
    try:
        await db.remove_replace_words(message.from_user.id, [target])
        await message.reply_text(f"**रिप्लेसमेंट हटाया गया:** `{target}`")
    except Exception as e:
        await message.reply_text(f"**Error:** `{e}`")

# Rexbots
# Don't Remove Credit
# Telegram Channel @RexBots_Official

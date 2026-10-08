# ==============================================================================
# Ultra-Fast Universal Content Saver & Topic Router Bot (Full 30 Commands)
# Supports: Public Channels/Groups, Private Channels/Topics, Forum Supergroups
# ==============================================================================

import os
import re
import asyncio
import shutil
import logging
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait, RPCError, SessionPasswordNeeded, PhoneCodeInvalid, PasswordHashInvalid
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from config import API_ID, API_HASH
from database.db import db

# अगर कॉन्फिग में ग्लोबल स्ट्रिंग सेशन मौजूद हो
try:
    from config import STRING_SESSION
except ImportError:
    STRING_SESSION = None

logger = logging.getLogger(__name__)

class State:
    IS_BUSY = {}
    CLEAN_ADS = {}
    PREFIX = {}
    SUFFIX = {}
    TOPIC_KEYWORD_MAP = {}
    TOPIC_DIRECT_MAP = {}
    DEFAULT_TOPIC = {}
    LOGIN_DATA = {}
    CUSTOM_CAPTION = {}
    THUMBNAIL = {}
    REPLACE_WORDS = {}
    DELETE_WORDS = {}
    LOADED = set()


# --- Saved preferences (survive restarts) ---
async def load_prefs(user_id: int):
    if user_id in State.LOADED:
        return
    try:
        data = await db.get_prefs(user_id)
    except Exception as e:
        logger.warning(f"load_prefs failed: {e}")
        data = {}
    if data.get("clean_ads"):
        State.CLEAN_ADS[user_id] = True
    if data.get("prefix"):
        State.PREFIX[user_id] = data["prefix"]
    if data.get("suffix"):
        State.SUFFIX[user_id] = data["suffix"]
    if data.get("default_topic") is not None:
        State.DEFAULT_TOPIC[user_id] = int(data["default_topic"])
    if data.get("topic_keywords"):
        State.TOPIC_KEYWORD_MAP[user_id] = {k: int(v) for k, v in data["topic_keywords"].items()}
    if data.get("topic_direct"):
        State.TOPIC_DIRECT_MAP[user_id] = {int(k): int(v) for k, v in data["topic_direct"].items()}
    State.LOADED.add(user_id)

async def save_prefs(user_id: int):
    data = {
        "clean_ads": bool(State.CLEAN_ADS.get(user_id, False)),
        "prefix": State.PREFIX.get(user_id, ""),
        "suffix": State.SUFFIX.get(user_id, ""),
        "default_topic": State.DEFAULT_TOPIC.get(user_id),
        "topic_keywords": State.TOPIC_KEYWORD_MAP.get(user_id, {}),
        "topic_direct": {str(k): v for k, v in State.TOPIC_DIRECT_MAP.get(user_id, {}).items()},
    }
    try:
        await db.set_prefs(user_id, data)
    except Exception as e:
        logger.warning(f"save_prefs failed: {e}")

@Client.on_message(filters.private & filters.incoming, group=-3)
async def _prefs_loader(bot: Client, message: Message):
    if message.from_user:
        await load_prefs(message.from_user.id)

# --- 1. सटीक लिंक पार्सर ---
def parse_tg_link(url: str):
    url = url.split("?")[0].strip()
    
    # Private Forum Topic: t.me/c/CHAT_ID/TOPIC_ID/MSG_ID
    m_priv_topic = re.search(r"t\.me/c/(\d+)/(\d+)/(\d+)", url)
    if m_priv_topic:
        return int("-100" + m_priv_topic.group(1)), int(m_priv_topic.group(3)), int(m_priv_topic.group(2))
        
    # Private Normal: t.me/c/CHAT_ID/MSG_ID
    m_priv = re.search(r"t\.me/c/(\d+)/(\d+)", url)
    if m_priv:
        return int("-100" + m_priv.group(1)), int(m_priv.group(2)), None
        
    # Public Forum Topic: t.me/USERNAME/TOPIC_ID/MSG_ID
    m_pub_topic = re.search(r"t\.me/([^/]+)/(\d+)/(\d+)", url)
    if m_pub_topic:
        return m_pub_topic.group(1), int(m_pub_topic.group(3)), int(m_pub_topic.group(2))
        
    # Public Normal: t.me/USERNAME/MSG_ID
    m_pub = re.search(r"t\.me/([^/]+)/(\d+)", url)
    if m_pub:
        return m_pub.group(1), int(m_pub.group(2)), None
        
    return None, None, None

def get_media_type(msg: Message):
    for media_type in ['video', 'document', 'photo', 'audio', 'voice', 'text']:
        if getattr(msg, media_type, None):
            return media_type.capitalize()
    return None

def resolve_target_topic(user_id: int, msg: Message, source_topic: int = None) -> int:
    # 1. डायरेक्ट टॉपिक मैपिंग
    if source_topic and user_id in State.TOPIC_DIRECT_MAP:
        if source_topic in State.TOPIC_DIRECT_MAP[user_id]:
            return State.TOPIC_DIRECT_MAP[user_id][source_topic]

    # 2. कीवर्ड आधारित मैपिंग
    kw_map = State.TOPIC_KEYWORD_MAP.get(user_id, {})
    if kw_map:
        search_str = (msg.caption or msg.text or "").lower()
        if msg.video and getattr(msg.video, 'file_name', None):
            search_str += " " + msg.video.file_name.lower()
        elif msg.document and getattr(msg.document, 'file_name', None):
            search_str += " " + msg.document.file_name.lower()

        for keyword, t_id in kw_map.items():
            if re.search(r'\b' + re.escape(keyword) + r'\b', search_str, re.IGNORECASE) or keyword in search_str:
                return t_id

    # 3. सोर्स टॉपिक या डिफ़ॉल्ट टॉपिक
    if source_topic:
        return source_topic

    return State.DEFAULT_TOPIC.get(user_id, None)

async def load_user_settings(user_id: int):
    st = {"caption": None, "replace": {}, "delete": [], "thumb": None}
    try:
        st["caption"] = await db.get_caption(user_id)
        st["replace"] = await db.get_replace_words(user_id) or {}
        st["delete"] = await db.get_delete_words(user_id) or []
        st["thumb"] = await db.get_thumbnail(user_id)
    except Exception as e:
        logger.warning(f"load_user_settings failed: {e}")
    return st

def _human_size(n):
    n = float(n or 0)
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024

def format_caption(user_id: int, st: dict, msg: Message, caption: str, allow_custom: bool = True) -> str:
    custom = st.get("caption")
    if custom and allow_custom:
        media = msg.video or msg.document or msg.audio or msg.voice or msg.photo
        file_name = getattr(media, "file_name", None) or ""
        size_text = _human_size(getattr(media, "file_size", 0)) if media else ""
        return custom.replace("{filename}", file_name).replace("{size}", size_text)

    if not caption:
        return ""

    if State.CLEAN_ADS.get(user_id, False):
        caption = re.sub(r'(https?://\S+|t\.me/\S+)', '', caption)
        caption = re.sub(r'@[a-zA-Z0-9_]+', '', caption)
        caption = re.sub(r'Join\s*:\s*\S+', '', caption, flags=re.IGNORECASE)

    for old, new in (st.get("replace") or {}).items():
        caption = caption.replace(old, new)
    for w in (st.get("delete") or []):
        caption = caption.replace(w, "")

    prefix = State.PREFIX.get(user_id, "")
    suffix = State.SUFFIX.get(user_id, "")
    if prefix: caption = f"{prefix}\n\n{caption}"
    if suffix: caption = f"{caption}\n\n{suffix}"
    return caption.strip()

# --- 2. यूजर कमांड्स ---

@Client.on_message(filters.command(["start"]))
async def start_handler(bot: Client, message: Message):
    text = (
        f"👋 <b>नमस्ते {message.from_user.mention}!</b>\n\n"
        "⚡ <b>फास्ट टॉपिक व चैनल फॉरवर्डिंग बॉट सक्रिय है (प्लान के साथ)।</b>\n\n"
        "• टारगेट चैनल/ग्रुप सेट करें: <code>/setchat -100xxxxxxxxxx</code>\n"
        "• बोट में ही वीडियो पाने के लिए: <code>/clearchat</code> या <code>/setchat clear</code>\n"
        "• विषय अनुसार टॉपिक सेट करें: <code>/set_topics</code>\n"
        "• डिफ़ॉल्ट टॉपिक सेट करें: <code>/settopic &lt;topic_id&gt;</code>\n"
        "• प्राइवेट लिंक लॉगिन करें: <code>/login</code>\n"
        "• सभी कमांड्स देखने के लिए: <code>/help</code>\n"
        "• चालू टास्क रोकें: <code>/cancel</code>\n\n"
        "📌 <b>उपयोग:</b> प्राइवेट या पब्लिक लिंक भेजें (उदा: <code>https://t.me/c/123/10</code> या रेंज <code>https://t.me/c/123/10-20</code>)"
    )
    await message.reply_text(text, parse_mode=enums.ParseMode.HTML)

@Client.on_message(filters.command(["help"]) & filters.private)
async def help_handler(bot: Client, message: Message):
    help_text = (
        "📖 <b>सभी उपलब्ध कमांड्स की सूची:</b>\n\n"
        "• <code>/start</code> - बॉट शुरू करें\n"
        "• <code>/help</code> - सहायता मेनू देखें\n"
        "• <code>/settings</code> - वर्तमान सेटिंग्स देखें\n"
        "• <code>/login</code> - टेलीग्राम अकाउंट लॉगिन करें\n"
        "• <code>/logout</code> - अकाउंट लॉगआउट करें\n"
        "• <code>/cancel</code> - चालू फॉरवर्डिंग टास्क रोकें\n"
        "• <code>/myplan</code> - अपना प्लान स्टेटस देखें\n"
        "• <code>/premium</code> - प्रीमियम प्लान की जानकारी\n"
        "• <code>/setchat -100xxxxxxxxxx</code> - फॉरवर्ड चैनल सेट करें\n"
        "• <code>/clearchat</code> - चैनल फॉरवर्डिंग बंद करें\n"
        "• <code>/set_topics</code> - बल्क टॉपिक कीवर्ड्स सेट करें\n"
        "• <code>/settopic &lt;id&gt;</code> - डिफ़ॉल्ट टॉपिक सेट करें\n"
        "• <code>/map_topic &lt;src&gt; &lt;dest&gt;</code> - डायरेक्ट टॉपिक मैप करें\n"
        "• <code>/show_topics</code> - सक्रिय टॉपिक लिस्ट देखें\n"
        "• <code>/reset_topics</code> - सभी टॉपिक मैपिंग हटाएं\n"
        "• <code>/set_thumb</code> - फोटो रिप्लाई करके थंबनेल सेट करें\n"
        "• <code>/view_thumb</code> - वर्तमान थंबनेल देखें\n"
        "• <code>/del_thumb</code> - थंबनेल हटाएं\n"
        "• <code>/set_caption &lt;text&gt;</code> - कस्टम कैप्शन लगाएं\n"
        "• <code>/see_caption</code> - वर्तमान कैप्शन देखें\n"
        "• <code>/del_caption</code> - कस्टम कैप्शन हटाएं\n"
        "• <code>/clean_ads on|off</code> - एड्स ऑटो-क्लीन ऑन/ऑफ करें\n"
        "• <code>/prefix &lt;text&gt;</code> - कैप्शन के शुरू में जोड़ें\n"
        "• <code>/suffix &lt;text&gt;</code> - कैप्शन के अंत में जोड़ें\n"
        "• <code>/set_repl_word &lt;पुराना&gt; &lt;नया&gt;</code> - शब्द बदलें\n"
        "• <code>/rem_repl_word &lt;old&gt;</code> - रिप्लेस लिस्ट से हटाएं\n"
        "• <code>/clear_replace</code> - सभी रिप्लेसमेंट नियम हटाएं\n"
        "• <code>/set_del_word &lt;word&gt;</code> - डिलीट करने का शब्द जोड़ें\n"
        "• <code>/rem_del_word &lt;word&gt;</code> - डिलीट लिस्ट से शब्द हटाएं"
    )
    await message.reply_text(help_text, parse_mode=enums.ParseMode.HTML)

@Client.on_message(filters.command(["clearchat"]) & filters.private)
async def clear_chat_cmd(bot: Client, message: Message):
    user_id = message.from_user.id
    if hasattr(db, "col"):
        await db.col.update_one({"_id": user_id}, {"$unset": {"dump_chat": 1}})
    else:
        await db.set_dump_chat(user_id, None)
    State.DEFAULT_TOPIC.pop(user_id, None)
    await save_prefs(user_id)
    await message.reply_text("✅ टारगेट चैट हटा दी गई है। फाइलें अब पर्सनल बॉट चैट में आएँगी।")

@Client.on_message(filters.command(["set_topics"]) & filters.private)
async def set_topics_bulk(bot: Client, message: Message):
    content = message.text.replace("/set_topics", "").strip()
    if not content:
        return await message.reply_text(
            "<b>फॉर्मेट उदाहरण:</b>\n"
            "<code>/set_topics\n"
            "Maths: https://t.me/c/3635348530/7\n"
            "Reasoning: https://t.me/c/3635348530/8\n"
            "History: https://t.me/c/3635348530/11</code>",
            parse_mode=enums.ParseMode.HTML
        )
    mapping = {}
    for line in content.split("\n"):
        if ":" in line:
            name, link = line.split(":", 1)
            name = name.strip().lower()
            match = re.search(r"/(\d+)$", link.strip())
            if match:
                mapping[name] = int(match.group(1))

    if not mapping:
        return await message.reply_text("❌ कोई मान्य टॉपिक लिंक नहीं मिला।")

    State.TOPIC_KEYWORD_MAP[message.from_user.id] = mapping
    await save_prefs(message.from_user.id)
    res = "<b>✅ टॉपिक कीवर्ड्स मैप हो गए:</b>\n\n"
    for k, v in mapping.items():
        res += f"• <b>{k.title()}</b> ➔ Topic ID: <code>{v}</code>\n"
    await message.reply_text(res, parse_mode=enums.ParseMode.HTML)

@Client.on_message(filters.command(["settopic"]) & filters.private)
async def set_single_topic(bot: Client, message: Message):
    args = message.text.split()
    if len(args) < 2 or args[1].lower() == "clear":
        State.DEFAULT_TOPIC.pop(message.from_user.id, None)
        await save_prefs(message.from_user.id)
        return await message.reply_text("✅ डिफ़ॉल्ट टॉपिक हटा दिया गया।")
    try:
        t_id = int(args[1])
        State.DEFAULT_TOPIC[message.from_user.id] = t_id
        await save_prefs(message.from_user.id)
        await message.reply_text(f"✅ डिफ़ॉल्ट टॉपिक सेट हुआ: <code>{t_id}</code>")
    except ValueError:
        await message.reply_text("❌ कृपया केवल संख्यात्मक ID दर्ज करें।")

@Client.on_message(filters.command(["map_topic"]) & filters.private)
async def map_topic_cmd(bot: Client, message: Message):
    args = message.text.split()
    if len(args) < 3:
        return await message.reply_text("उपयोग: <code>/map_topic &lt;source_topic_id&gt; &lt;target_topic_id&gt;</code>", parse_mode=enums.ParseMode.HTML)
    try:
        src = int(args[1])
        dest = int(args[2])
        if message.from_user.id not in State.TOPIC_DIRECT_MAP:
            State.TOPIC_DIRECT_MAP[message.from_user.id] = {}
        State.TOPIC_DIRECT_MAP[message.from_user.id][src] = dest
        await save_prefs(message.from_user.id)
        await message.reply_text(f"✅ टॉपिक मैप हुआ: <code>{src}</code> ➔ <code>{dest}</code>", parse_mode=enums.ParseMode.HTML)
    except ValueError:
        await message.reply_text("❌ दोनों टॉपिक ID केवल संख्यात्मक होने चाहिए।")

@Client.on_message(filters.command(["show_topics"]) & filters.private)
async def show_topics_cmd(bot: Client, message: Message):
    user_id = message.from_user.id
    kw_map = State.TOPIC_KEYWORD_MAP.get(user_id, {})
    dir_map = State.TOPIC_DIRECT_MAP.get(user_id, {})

    if not kw_map and not dir_map:
        return await message.reply_text("ℹ️ वर्तमान में कोई टॉपिक मैपिंग सेट नहीं है।")

    res = "📌 <b>सक्रिय टॉपिक मैपिंग:</b>\n\n"
    if kw_map:
        res += "<b>कीवर्ड मैपिंग:</b>\n"
        for k, v in kw_map.items():
            res += f"• <code>{k.title()}</code> ➔ Topic: <code>{v}</code>\n"
    if dir_map:
        res += "\n<b>डायरेक्ट टॉपिक मैपिंग:</b>\n"
        for s, d in dir_map.items():
            res += f"• <code>{s}</code> ➔ <code>{d}</code>\n"
    await message.reply_text(res, parse_mode=enums.ParseMode.HTML)

@Client.on_message(filters.command(["reset_topics"]) & filters.private)
async def reset_topics_cmd(bot: Client, message: Message):
    user_id = message.from_user.id
    State.TOPIC_KEYWORD_MAP.pop(user_id, None)
    State.TOPIC_DIRECT_MAP.pop(user_id, None)
    State.DEFAULT_TOPIC.pop(user_id, None)
    await save_prefs(user_id)
    await message.reply_text("🗑️ सभी टॉपिक सेटिंग्स और मैपिंग को सफलतापूर्वक हटा दिया गया है।")

@Client.on_message(filters.command(["clean_ads"]) & filters.private)
async def clean_ads_cmd(bot: Client, message: Message):
    args = message.text.split()
    user_id = message.from_user.id
    if len(args) < 2 or args[1].lower() not in ["on", "off"]:
        curr = "ON" if State.CLEAN_ADS.get(user_id, False) else "OFF"
        return await message.reply_text(f"उपयोग: <code>/clean_ads on</code> या <code>off</code> (वर्तमान: <b>{curr}</b>)", parse_mode=enums.ParseMode.HTML)
    status = args[1].lower() == "on"
    State.CLEAN_ADS[user_id] = status
    await save_prefs(user_id)
    await message.reply_text(f"✅ विज्ञापन क्लीनर: <b>{'ON' if status else 'OFF'}</b>", parse_mode=enums.ParseMode.HTML)

@Client.on_message(filters.command(["prefix"]) & filters.private)
async def prefix_cmd(bot: Client, message: Message):
    args = message.text.split(None, 1)
    if len(args) < 2 or args[1].lower() == "clear":
        State.PREFIX.pop(message.from_user.id, None)
        await save_prefs(message.from_user.id)
        return await message.reply_text("✅ प्रीफिक्स हटा दिया गया।")
    State.PREFIX[message.from_user.id] = args[1].strip()
    await save_prefs(message.from_user.id)
    await message.reply_text(f"✅ प्रीफिक्स सेट हुआ: <code>{args[1].strip()}</code>", parse_mode=enums.ParseMode.HTML)

@Client.on_message(filters.command(["suffix"]) & filters.private)
async def suffix_cmd(bot: Client, message: Message):
    args = message.text.split(None, 1)
    if len(args) < 2 or args[1].lower() == "clear":
        State.SUFFIX.pop(message.from_user.id, None)
        await save_prefs(message.from_user.id)
        return await message.reply_text("✅ सफ़िक्स हटा दिया गया।")
    State.SUFFIX[message.from_user.id] = args[1].strip()
    await save_prefs(message.from_user.id)
    await message.reply_text(f"✅ सफ़िक्स सेट हुआ: <code>{args[1].strip()}</code>", parse_mode=enums.ParseMode.HTML)

@Client.on_message(filters.command(["clear_replace"]) & filters.private)
async def clear_replace_cmd(bot: Client, message: Message):
    await db.clear_replace_words(message.from_user.id)
    await message.reply_text("🗑️ सभी रिप्लेसमेंट नियम हटा दिए गए हैं।")

# कैंसिल बटन क्लिक (Interface Button Click)
@Client.on_callback_query(filters.regex("^cancel_task$"))
async def cancel_callback(bot: Client, query: CallbackQuery):
    user_id = query.from_user.id
    State.IS_BUSY[user_id] = False
    await query.answer("टास्क रोक दिया गया है!", show_alert=True)
    await query.message.edit_text("🛑 <b>फॉरवर्डिंग टास्क को रोक दिया गया है।</b>")

# --- 4. कोर एक्सट्रैक्टर और फॉरवर्डिंग इंजन ---

@Client.on_message(filters.text & filters.private & ~filters.regex("^/"))
async def universal_forwarder(bot: Client, message: Message):
    if "t.me/" not in message.text:
        return

    user_id = message.from_user.id
    if State.IS_BUSY.get(user_id, False):
        return await message.reply_text("⚠️ एक टास्क पहले से चालू है। इसे रोकने के लिए <code>/cancel</code> भेजें।")

    raw_text = message.text.strip()
    range_match = re.search(r"-(\d+)$", raw_text)
    to_msg_id = int(range_match.group(1)) if range_match else None
    base_link = re.sub(r"-\d+$", "", raw_text)

    source_chat, from_msg_id, link_topic_id = parse_tg_link(base_link)
    if not source_chat or not from_msg_id:
        return await message.reply_text("❌ <b>अमान्य टेलीग्राम लिंक।</b> सही लिंक भेजें।")

    to_msg_id = to_msg_id or from_msg_id
    if to_msg_id < from_msg_id:
        to_msg_id = from_msg_id

    # टारगेट चैट और फोरम सपोर्ट
    dump_chat_id = await db.get_dump_chat(user_id) if hasattr(db, "get_dump_chat") else None
    target_chat = dump_chat_id if dump_chat_id else message.chat.id
    is_forum = False
    if target_chat != message.chat.id:
        try:
            t_obj = await bot.get_chat(target_chat)
            if t_obj.type == enums.ChatType.SUPERGROUP and getattr(t_obj, 'is_forum', False):
                is_forum = True
        except Exception:
            pass

    # यूजर सेशन लोड
    user_client = None
    session_str = await db.get_session(user_id) or STRING_SESSION
    if session_str:
        try:
            user_client = Client(f"user_session_{user_id}", session_string=session_str, api_id=API_ID, api_hash=API_HASH, in_memory=True)
            await user_client.connect()
        except Exception as e:
            logger.warning(f"Session connect error: {e}")
            user_client = None

    if isinstance(source_chat, int) and not user_client:
        return await message.reply_text("🔒 <b>प्राइवेट चैनल/ग्रुप से फाइल निकालने के लिए पहले <code>/login</code> करें।</b>")

    user_settings = await load_user_settings(user_id)
    State.IS_BUSY[user_id] = True
    try:
        cancel_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_task")]])
        progress_msg = await message.reply_text(f"🚀 <b>टास्क शुरू हुआ:</b> <code>{from_msg_id}</code> से <code>{to_msg_id}</code>", reply_markup=cancel_keyboard)

        success_count = 0
        copy_works = True  # becomes False once the source chat is known to block forwarding
        for current_id in range(from_msg_id, to_msg_id + 1):
            if not State.IS_BUSY.get(user_id, False):
                break

            msg = None
            for client_instance in [user_client, bot]:
                if not client_instance:
                    continue
                try:
                    msg = await client_instance.get_messages(source_chat, current_id)
                    if msg and not msg.empty:
                        break
                except FloodWait as f:
                    await asyncio.sleep(f.value + 1)
                    msg = await client_instance.get_messages(source_chat, current_id)
                    break
                except RPCError:
                    continue

            if not msg or msg.empty:
                continue

            media_type = get_media_type(msg)
            if not media_type:
                continue

            source_topic = link_topic_id or getattr(msg, "message_thread_id", None)
            topic_to_post = resolve_target_topic(user_id, msg, source_topic)
            final_topic_id = topic_to_post if (is_forum and target_chat != message.chat.id) else None

            # 1. टेक्स्ट मैसेज
            if media_type == "Text":
                new_text = format_caption(user_id, user_settings, msg, msg.text or "", allow_custom=False)
                kwargs = {"chat_id": target_chat, "text": new_text}
                if final_topic_id:
                    kwargs["message_thread_id"] = final_topic_id
                try:
                    await bot.send_message(**kwargs)
                    success_count += 1
                except Exception as e:
                    logger.error(f"Text send failed: {e}")
                await asyncio.sleep(0.3)
                continue

            # 2. सुपर-फास्ट कॉपी
            new_caption = format_caption(user_id, user_settings, msg, msg.caption or "")
            copy_kwargs = {
                "chat_id": target_chat,
                "from_chat_id": source_chat,
                "message_id": current_id
            }
            if new_caption:
                copy_kwargs["caption"] = new_caption
            if final_topic_id:
                copy_kwargs["message_thread_id"] = final_topic_id

            copied = False
            if copy_works:
                for cl in [bot, user_client]:
                    if not cl:
                        continue
                    try:
                        await cl.copy_message(**copy_kwargs)
                        copied = True
                        success_count += 1
                        break
                    except FloodWait as f:
                        await asyncio.sleep(f.value + 1)
                        try:
                            await cl.copy_message(**copy_kwargs)
                            copied = True
                            success_count += 1
                            break
                        except Exception:
                            pass
                    except Exception as e:
                        if "RESTRICT" in (type(e).__name__ + str(e)).upper():
                            copy_works = False  # skip useless copy attempts for the rest of this batch
                            break

            # 3. रेस्ट्रिक्टेड कंटेंट डाउनलोड और री-अपलोड
            if not copied:
                temp_path = f"downloads/{user_id}_{current_id}"
                os.makedirs(temp_path, exist_ok=True)
                downloader = user_client if user_client else bot
                try:
                    dl_file = await downloader.download_media(msg, file_name=f"{temp_path}/")
                    send_kwargs = {"chat_id": target_chat, "caption": new_caption}
                    if final_topic_id:
                        send_kwargs["message_thread_id"] = final_topic_id

                    # कस्टम थंबनेल डाउनलोड/अप्लाई
                    user_thumb = user_settings.get("thumb")
                    thumb_path = None
                    if user_thumb and media_type in ["Video", "Document"]:
                        try:
                            thumb_path = await bot.download_media(user_thumb, file_name=f"{temp_path}/thumb.jpg")
                        except Exception:
                            thumb_path = None

                    if media_type == "Video":
                        await bot.send_video(**send_kwargs, video=dl_file, thumb=thumb_path, duration=getattr(msg.video, 'duration', 0))
                    elif media_type == "Document":
                        await bot.send_document(**send_kwargs, document=dl_file, thumb=thumb_path)
                    elif media_type == "Photo":
                        await bot.send_photo(**send_kwargs, photo=dl_file)
                    elif media_type == "Audio":
                        await bot.send_audio(**send_kwargs, audio=dl_file)
                    elif media_type == "Voice":
                        await bot.send_voice(**send_kwargs, voice=dl_file)

                    success_count += 1
                except Exception as dl_err:
                    logger.error(f"Download/Upload error on {current_id}: {dl_err}")
                finally:
                    if os.path.exists(temp_path):
                        shutil.rmtree(temp_path, ignore_errors=True)

            await asyncio.sleep(0.2 if not copied else 0.3)

    finally:
        if user_client:
            try:
                await user_client.disconnect()
            except Exception:
                pass
        State.IS_BUSY[user_id] = False

    await progress_msg.edit_text(f"✅ <b>टास्क पूरा हुआ!</b> कुल <code>{success_count}</code> मैसेज सफलतापूर्वक भेजे गए।")

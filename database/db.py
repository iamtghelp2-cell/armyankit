import motor.motor_asyncio
import datetime
from config import DB_NAME, DB_URI
from logger import LOGGER

logger = LOGGER(__name__)

class Database:
   
    def __init__(self, uri, database_name):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self._client[database_name]
        self.col = self.db.users

    def new_user(self, id, name):
        return dict(
            id = id,
            name = name,
            session = None,
            daily_usage = 0,
            limit_reset_time = None,
            is_premium = False,
            delete_words = [],
            replace_words = {},
            dump_chat = None
        )
   
    async def add_user(self, id, name):
        user = self.new_user(id, name)
        await self.col.insert_one(user)
        logger.info(f"New user added to DB: {id} - {name}")
   
    async def is_user_exist(self, id):
        user = await self.col.find_one({'id':int(id)})
        return bool(user)
   
    async def total_users_count(self):
        count = await self.col.count_documents({})
        return count

    async def get_all_users(self):
        return self.col.find({})

    async def delete_user(self, user_id):
        await self.col.delete_many({'id': int(user_id)})
        logger.info(f"User deleted from DB: {user_id}")

    async def set_session(self, id, session):
        await self.col.update_one({'id': int(id)}, {'$set': {'session': session}})

    async def get_session(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('session') if user else None

    # Dump Chat Support (यहाँ नया कोड जोड़ा गया है)
    async def set_dump_chat(self, id, chat_id):
        if chat_id is None:
            await self.col.update_one({'id': int(id)}, {'$unset': {'dump_chat': ""}})
            return
        await self.col.update_one(
            {'id': int(id)}, 
            {'$set': {'dump_chat': int(chat_id)}}, 
            upsert=True
        )

    async def get_dump_chat(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('dump_chat', None) if user else None

    async def del_dump_chat(self, id):
        await self.col.update_one(
            {'id': int(id)}, 
            {'$unset': {'dump_chat': ""}}
        )

    # Caption Support
    async def set_caption(self, id, caption):
        await self.col.update_one({'id': int(id)}, {'$set': {'caption': caption}})

    async def get_caption(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('caption', None) if user else None

    async def del_caption(self, id):
        await self.col.update_one({'id': int(id)}, {'$unset': {'caption': ""}})

    # Thumbnail Support
    async def set_thumbnail(self, id, thumbnail):
        await self.col.update_one({'id': int(id)}, {'$set': {'thumbnail': thumbnail}})

    async def get_thumbnail(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('thumbnail', None) if user else None

    async def del_thumbnail(self, id):
        await self.col.update_one({'id': int(id)}, {'$unset': {'thumbnail': ""}})

    # Premium Support
    async def add_premium(self, id, expiry_date):
        if not await self.is_user_exist(id):
            await self.add_user(int(id), "User")
        await self.col.update_one({'id': int(id)}, {
            '$set': {
                'is_premium': True,
                'premium_expiry': expiry_date,
                'daily_usage': 0,
                'limit_reset_time': None
            }
        })
        logger.info(f"User {id} granted premium until {expiry_date}")

    async def remove_premium(self, id):
        await self.col.update_one({'id': int(id)}, {'$set': {'is_premium': False, 'premium_expiry': None}})
        logger.info(f"User {id} removed from premium")

    async def check_premium(self, id):
        user = await self.col.find_one({'id': int(id)})
        if not user or not user.get('is_premium', False):
            return False
        expiry = user.get('premium_expiry')
        if not expiry:
            return True  # permanent
        try:
            if datetime.date.fromisoformat(str(expiry)[:10]) >= datetime.date.today():
                return True
        except Exception:
            return False
        await self.remove_premium(id)  # expired
        return False

    async def get_premium_users(self):
        return self.col.find({'is_premium': True})

    # Ban Support
    async def ban_user(self, id):
        await self.col.update_one({'id': int(id)}, {'$set': {'is_banned': True}})
        logger.warning(f"User banned: {id}")

    async def unban_user(self, id):
        await self.col.update_one({'id': int(id)}, {'$set': {'is_banned': False}})
        logger.info(f"User unbanned: {id}")

    async def is_banned(self, id):
        user = await self.col.find_one({'id': int(id)})
        if not user: return False
        return user.get('is_banned', False)

    # Delete Words Support
    async def set_delete_words(self, id, words):
        await self.col.update_one({'id': int(id)}, {'$addToSet': {'delete_words': {'$each': words}}}, upsert=True)

    async def get_delete_words(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('delete_words', []) if user else []

    async def remove_delete_words(self, id, words):
        await self.col.update_one({'id': int(id)}, {'$pull': {'delete_words': {'$in': words}}})

    # Replace Words Support
    async def set_replace_words(self, id, replace_dict):
        user = await self.col.find_one({'id': int(id)})
        current = user.get('replace_words', {}) if user else {}
        current.update(replace_dict)
        await self.col.update_one({'id': int(id)}, {'$set': {'replace_words': current}}, upsert=True)

    async def get_replace_words(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('replace_words', {}) if user else {}

    async def remove_replace_words(self, id, targets):
        user = await self.col.find_one({'id': int(id)})
        current = user.get('replace_words', {}) if user else {}
        for target in targets:
            current.pop(target, None)
        await self.col.update_one({'id': int(id)}, {'$set': {'replace_words': current}})

    async def clear_replace_words(self, id):
        await self.col.update_one({'id': int(id)}, {'$set': {'replace_words': {}}})

    # Saved preferences (prefix, suffix, topics...) - survive restarts
    async def get_prefs(self, id):
        user = await self.col.find_one({'id': int(id)})
        return (user.get('prefs') or {}) if user else {}

    async def set_prefs(self, id, prefs):
        await self.col.update_one({'id': int(id)}, {'$set': {'prefs': prefs}})

    # Limits Support
    async def check_limit(self, id):
        return False

    async def add_traffic(self, id):
        pass

db = Database(DB_URI, DB_NAME)

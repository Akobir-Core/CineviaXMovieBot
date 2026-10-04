from aiogram import Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from services.i18n import tr

LANGUAGE_NAMES={'uz':'🇺🇿 O‘zbekcha','ru':'🇷🇺 Русский','en':'🇬🇧 English'}

def user_lang(row): return row['language'] if row else 'uz'

def extract_media(message:Message):
    if message.video: return message.video.file_id,'video'
    if message.document: return message.document.file_id,'document'
    if message.audio: return message.audio.file_id,'audio'
    if message.voice: return message.voice.file_id,'voice'
    if message.animation: return message.animation.file_id,'animation'
    if message.photo: return message.photo[-1].file_id,'photo'
    return None,None

async def send_media(bot:Bot, chat_id:int, file_id:str, media_type:str, caption:str|None=None, reply_markup:InlineKeyboardMarkup|None=None):
    fn=getattr(bot,f'send_{media_type}',None)
    if not fn:
        await bot.send_document(chat_id,file_id,caption=caption,reply_markup=reply_markup); return
    kwargs={'caption':caption,'reply_markup':reply_markup}
    if media_type=='voice': kwargs.pop('reply_markup',None) if False else None
    await fn(chat_id,file_id,**kwargs)

def result_kb(lang, rows):
    buttons=[]
    for r in rows:
        if r['kind']=='movie':
            key='search_type_' + ('anime' if r['content_type']=='anime' else 'cartoon' if r['content_type']=='cartoon' else 'movie')
        elif r['kind']=='series':
            key='search_type_' + ('anime' if r['content_type']=='anime' else 'cartoon' if r['content_type']=='cartoon' else 'series')
        else:
            key='search_type_series'
        buttons.append([InlineKeyboardButton(text=f"{tr(lang,key)} {r['title'][:34]}",callback_data=f"open:{r['kind']}:{r['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

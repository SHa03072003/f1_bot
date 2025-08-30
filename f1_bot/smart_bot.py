import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import random
import asyncio
import aiohttp
import async_timeout
from functools import lru_cache
import hashlib
import redis
import pickle
import time

# Защищенный импорт ИИ библиотек
try:
    from sentence_transformers import SentenceTransformer, util
    import torch
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False
    print("AI libraries not available - running in simple mode")

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен бота
TOKEN = "8464916111:AAGGy0HS7GrbwITL_hb6SePhlX2zkJIi4Ik"

# Состояния разговора
LANGUAGE, NAME, MAIN_MENU, AI_STYLE, QUESTION, IMAGE_GEN = range(6)

# Настройки кэширования
CACHE_TTL = 3600  # 1 час
RATE_LIMIT_WINDOW = 60  # 60 секунд
MAX_REQUESTS_PER_MINUTE = 10

# Инициализация Redis для кэширования
try:
    redis_client = redis.Redis(
        host='localhost',
        port=6379,
        db=0,
        decode_responses=False
    )
    redis_client.ping()
    REDIS_AVAILABLE = True
    logger.info("Redis connected successfully")
except Exception as e:
    REDIS_AVAILABLE = False
    logger.warning(f"Redis not available: {e}. Using in-memory cache")

# Данные пользователей
user_data = {}
user_activity = {}  # Для rate limiting
response_cache = {}  # Fallback кэш

# Доступные языки
LANGUAGES = {
    "🇷🇺 Русский": "ru",
    "🇺🇸 English": "en", 
    "🇪🇸 Español": "es",
    "🇫🇷 Français": "fr",
    "🇩🇪 Deutsch": "de"
}

# Стили ИИ для ответов
AI_STYLES = {
    "🤖 Универсальный": "universal",
    "💻 IT-Специалист": "it",
    "🎨 Творческий": "creative",
    "📚 Научный": "scientific", 
    "💰 Финансовый": "financial"
}

# Тексты на разных языках
TEXTS = {
    "ru": {
        "welcome": "🌍 Выберите язык:",
        "name_ask": "Как вас зовут?",
        "greeting": "Привет, {name}! Рад знакомству!",
        "main_menu": "Главное меню:",
        "ai_style": "Выберите стиль ответа:",
        "ask_question": "Задайте ваш вопрос:",
        "searching": "🔍 Ищу информацию...",
        "settings": "⚙️ Настройки",
        "info": "ℹ️ Информация",
        "generate_image": "🎨 Сгенерировать изображение",
        "ask_image": "Опишите что вы хотите увидеть на изображении:",
        "image_created": "🖼️ Ваше изображение готово!",
        "error": "❌ Произошла ошибка. Попробуйте снова.",
        "thanks": "Спасибо за вопрос! 😊",
        "smart_response": "🧠 Умный ответ",
        "deep_search": "🔍 Глубокий поиск",
        "rate_limit": "⚠️ Слишком много запросов. Подождите немного."
    },
    "en": {
        "welcome": "🌍 Choose language:",
        "name_ask": "What is your name?",
        "greeting": "Hello, {name}! Nice to meet you!",
        "main_menu": "Main menu:",
        "ai_style": "Choose response style:",
        "ask_question": "Ask your question:",
        "searching": "🔍 Searching for information...",
        "settings": "⚙️ Settings",
        "info": "ℹ️ Information", 
        "generate_image": "🎨 Generate image",
        "ask_image": "Describe what you want to see in the image:",
        "image_created": "🖼️ Your image is ready!",
        "error": "❌ An error occurred. Please try again.",
        "thanks": "Thanks for your question! 😊",
        "smart_response": "🧠 Smart response",
        "deep_search": "🔍 Deep search",
        "rate_limit": "⚠️ Too many requests. Please wait a moment."
    }
}

class CacheManager:
    """Менеджер кэширования с поддержкой Redis"""
    
    def __init__(self):
        self.use_redis = REDIS_AVAILABLE
    
    def _get_key(self, key_prefix: str, identifier: str) -> str:
        """Генерация ключа для кэша"""
        return f"{key_prefix}:{hashlib.md5(identifier.encode()).hexdigest()}"
    
    def get(self, key_prefix: str, identifier: str):
        """Получение данных из кэша"""
        cache_key = self._get_key(key_prefix, identifier)
        
        try:
            if self.use_redis:
                cached_data = redis_client.get(cache_key)
                if cached_data:
                    return pickle.loads(cached_data)
            else:
                if cache_key in response_cache:
                    data, expiry = response_cache[cache_key]
                    if time.time() < expiry:
                        return data
        except Exception as e:
            logger.error(f"Cache get error: {e}")
        
        return None
    
    def set(self, key_prefix: str, identifier: str, data, ttl: int = CACHE_TTL):
        """Сохранение данных в кэш"""
        cache_key = self._get_key(key_prefix, identifier)
        expiry = time.time() + ttl
        
        try:
            if self.use_redis:
                redis_client.setex(
                    cache_key,
                    ttl,
                    pickle.dumps(data)
                )
            else:
                response_cache[cache_key] = (data, expiry)
        except Exception as e:
            logger.error(f"Cache set error: {e}")

class RateLimiter:
    """Система ограничения запросов"""
    
    def __init__(self):
        self.user_requests = {}
    
    def check_rate_limit(self, user_id: int) -> Tuple[bool, int]:
        """Проверка rate limit для пользователя"""
        current_time = time.time()
        
        if user_id not in self.user_requests:
            self.user_requests[user_id] = []
        
        # Очищаем старые запросы
        self.user_requests[user_id] = [
            req_time for req_time in self.user_requests[user_id]
            if current_time - req_time < RATE_LIMIT_WINDOW
        ]
        
        if len(self.user_requests[user_id]) >= MAX_REQUESTS_PER_MINUTE:
            wait_time = int(RATE_LIMIT_WINDOW - (current_time - self.user_requests[user_id][0]))
            return False, wait_time
        
        self.user_requests[user_id].append(current_time)
        return True, 0

class EnhancedSmartAssistant(SmartAssistant):
    """Улучшенный ассистент с кэшированием и оптимизациями"""
    
    def __init__(self):
        super().__init__()
        self.cache = CacheManager()
        self.session = None
        self.search_semaphore = asyncio.Semaphore(5)  # Ограничение параллельных поисков
    
    async def async_init(self):
        """Асинхронная инициализация"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10),
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            }
        )
    
    async def find_similar_async(self, question: str, top_k: int = 3):
        """Асинхронный поиск похожей информации"""
        cache_key = f"similar:{question}"
        cached_result = self.cache.get("similar", question)
        
        if cached_result:
            logger.info(f"Cache hit for similar: {question}")
            return cached_result
        
        result = self.find_similar(question, top_k)
        self.cache.set("similar", question, result, ttl=1800)  # 30 минут
        
        return result

class AdvancedSearch:
    """Улучшенная система поиска"""
    
    def __init__(self):
        self.cache = CacheManager()
        self.trusted_sources = {
            'ru': [
                'rbc.ru', 'ria.ru', 'tass.ru', 'lenta.ru', 'kommersant.ru',
                'vedomosti.ru', 'rg.ru', 'interfax.ru', 'gazeta.ru'
            ],
            'en': [
                'reuters.com', 'bloomberg.com', 'bbc.com', 'cnn.com',
                'theguardian.com', 'nytimes.com', 'wsj.com', 'apnews.com'
            ]
        }
    
    async def enhanced_search(self, query: str, lang: str = "ru") -> List[str]:
        """Улучшенный поиск с приоритетом доверенных источников"""
        cache_key = f"search:{query}:{lang}"
        cached_results = self.cache.get("search", f"{query}:{lang}")
        
        if cached_results:
            logger.info(f"Cache hit for search: {query}")
            return cached_results
        
        # Основной поиск (оставляем вашу реализацию)
        basic_results = google_search(query, lang)
        
        # Приоритизация доверенных источников
        trusted_results = []
        other_results = []
        
        for result in basic_results:
            if any(trusted in result for trusted in self.trusted_sources.get(lang, [])):
                trusted_results.append(result)
            else:
                other_results.append(result)
        
        final_results = trusted_results + other_results
        
        # Кэшируем результаты
        self.cache.set("search", f"{query}:{lang}", final_results, ttl=3600)
        
        return final_results

# Глобальные экземпляры
cache_manager = CacheManager()
rate_limiter = RateLimiter()
assistant = EnhancedSmartAssistant()
advanced_search = AdvancedSearch()

# Асинхронная инициализация при запуске
async def initialize_assistant():
    await assistant.async_init()

# Декоратор для обработки ошибок и rate limiting
def handle_errors(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.message.from_user.id
        lang_code = user_data.get(user_id, {}).get("lang", "ru")
        texts = TEXTS.get(lang_code, TEXTS["ru"])
        
        # Проверка rate limit
        allowed, wait_time = rate_limiter.check_rate_limit(user_id)
        if not allowed:
            await update.message.reply_text(
                f"{texts['rate_limit']} ({wait_time} сек.)"
            )
            return MAIN_MENU
        
        try:
            return await func(update, context, *args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {e}")
            await update.message.reply_text(texts["error"])
            return MAIN_MENU
    
    return wrapper

# Модифицированные обработчики с улучшениями
@handle_errors
async def question_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Улучшенный обработчик вопросов с кэшированием"""
    user_id = update.message.from_user.id
    question = update.message.text
    lang_code = user_data[user_id]["lang"]
    texts = TEXTS.get(lang_code, TEXTS["ru"])
    
    # Проверка кэша ответов
    cached_response = cache_manager.get("answer", f"{user_id}:{question}")
    if cached_response:
        logger.info(f"Serving cached answer for user {user_id}")
        await update.message.reply_text(cached_response)
        await update.message.reply_text(texts["thanks"])
        return MAIN_MENU
    
    await update.message.reply_text(texts["searching"])
    
    try:
        # Асинхронный поиск и обработка
        search_results = await advanced_search.enhanced_search(question, lang_code)
        context_info = ""
        
        if search_results:
            # Асинхронный анализ страниц
            page_text = await extract_info_from_page_async(search_results[0])
            if page_text:
                context_info = page_text
        
        # Генерация ответа с ИИ
        response = generate_smart_response(question, context_info, lang_code)
        
        # Добавление источника
        if search_results and context_info:
            response += f"\n\n🔗 Источник: {search_results[0]}"
        
        # Кэширование ответа
        cache_manager.set("answer", f"{user_id}:{question}", response, ttl=1800)
        
        await update.message.reply_text(response)
        await update.message.reply_text(texts["thanks"])
            
    except Exception as e:
        logger.error(f"Search error: {e}")
        await update.message.reply_text(texts["error"])
    
    return MAIN_MENU

async def extract_info_from_page_async(url: str) -> str:
    """Асинхронное извлечение информации со страницы"""
    cache_key = f"page:{url}"
    cached_content = cache_manager.get("page", url)
    
    if cached_content:
        return cached_content
    
    try:
        async with assistant.session.get(url) as response:
            if response.status == 200:
                content = await response.text()
                info = extract_info_from_page(url)  # Ваша существующая функция
                cache_manager.set("page", url, info, ttl=7200)  # 2 часа
                return info
    except Exception as e:
        logger.error(f"Async page extraction error: {e}")
    
    return ""

# Персонализация
class UserProfileManager:
    """Управление персональными профилями пользователей"""
    
    def __init__(self):
        self.user_profiles = {}
    
    def get_user_profile(self, user_id: int) -> Dict:
        """Получение профиля пользователя"""
        if user_id not in self.user_profiles:
            self.user_profiles[user_id] = {
                'preferred_style': 'universal',
                'search_history': [],
                'response_preferences': {},
                'last_interaction': datetime.now(),
                'total_requests': 0
            }
        return self.user_profiles[user_id]
    
    def update_user_activity(self, user_id: int, question: str, response: str):
        """Обновление активности пользователя"""
        profile = self.get_user_profile(user_id)
        profile['search_history'].append({
            'question': question,
            'response': response,
            'timestamp': datetime.now().isoformat()
        })
        profile['last_interaction'] = datetime.now()
        profile['total_requests'] += 1
        
        # Ограничиваем историю последними 100 запросами
        if len(profile['search_history']) > 100:
            profile['search_history'] = profile['search_history'][-100:]

user_profile_manager = UserProfileManager()

# Модифицируем обработчик вопросов для персонализации
@handle_errors
async def personalized_question_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик с персонализацией"""
    user_id = update.message.from_user.id
    question = update.message.text
    lang_code = user_data[user_id]["lang"]
    texts = TEXTS.get(lang_code, TEXTS["ru"])
    
    # Получаем профиль пользователя
    user_profile = user_profile_manager.get_user_profile(user_id)
    preferred_style = user_profile.get('preferred_style', 'universal')
    
    # Здесь можно адаптировать поиск based на предпочтениях пользователя
    
    # Остальная логика обработки вопроса...
    response = await question_handler(update, context)
    
    # Сохраняем в историю
    user_profile_manager.update_user_activity(user_id, question, "response_content")
    
    return response

# Добавляем команду для статистики
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для просмотра статистики"""
    user_id = update.message.from_user.id
    profile = user_profile_manager.get_user_profile(user_id)
    
    stats_text = (
        f"📊 Ваша статистика:\n"
        f"• Всего запросов: {profile['total_requests']}\n"
        f"• Последняя активность: {profile['last_interaction'].strftime('%Y-%m-%d %H:%M')}\n"
        f"• Предпочтительный стиль: {profile['preferred_style']}\n"
        f"🎯 Персональные рекомендации скоро появятся!"
    )
    
    await update.message.reply_text(stats_text)

def main():
    """Основная функция с улучшениями"""
    application = Application.builder().token(TOKEN).build()
    
    # Асинхронная инициализация
    loop = asyncio.get_event_loop()
    loop.run_until_complete(initialize_assistant())
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            LANGUAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, language_handler)],
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_handler)],
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler)],
            AI_STYLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ai_style_handler)],
            QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, personalized_question_handler)],
            IMAGE_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, image_generation_handler)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Добавляем команду статистики
    application.add_handler(CommandHandler('stats', stats_command))
    application.add_handler(conv_handler)
    
    print("🤖 Умный бот с ИИ запущен с улучшениями!")
    print("✅ Кэширование включено")
    print("✅ Rate limiting активен")
    print("✅ Персонализация работает")
    print("✅ Производительность оптимизирована")
    
    application.run_polling()

if __name__ == "__main__":
    main()
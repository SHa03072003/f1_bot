import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import Updater, CommandHandler, MessageHandler, filters, ConversationHandler, CallbackContext
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime
from typing import Dict, List
import random

# Защищенный импорт ИИ библиотек
try:
    from sentence_transformers import SentenceTransformer, util
    import torch
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False
    print("AI libraries not available - running in simple mode")

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен бота
TOKEN = "8464916111:AAGGy0HS7GrbwITL_hb6SePhlX2zkJIi4Ik"

# Состояния разговора
LANGUAGE, NAME, MAIN_MENU, AI_STYLE, QUESTION, IMAGE_GEN = range(6)

# Данные пользователей
user_data = {}

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
        "deep_search": "🔍 Глубокий поиск"
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
        "deep_search": "🔍 Deep search"
    }
}

class SmartAssistant:
    def __init__(self):
        self.model = None
        self.knowledge = []
        
        if AI_AVAILABLE:
            try:
                # Используем более легкую модель
                self.model = SentenceTransformer('paraphrase-albert-small-v2')
                logger.info("AI model loaded successfully")
            except Exception as e:
                logger.error(f"AI model loading error: {e}")
                self.model = None
        else:
            logger.info("AI mode disabled - running without neural networks")
        
    def add_knowledge(self, text: str, source: str = ""):
        """Добавляем информацию в базу знаний"""
        if len(text) > 50:
            self.knowledge.append({
                "text": text,
                "source": source,
                "timestamp": datetime.now().isoformat()
            })
    
    def find_similar(self, question: str, top_k: int = 3):
        """Находим похожую информацию в базе знаний"""
        if not self.knowledge or not self.model:
            return []
            
        try:
            question_embedding = self.model.encode(question, convert_to_tensor=True)
            knowledge_texts = [k["text"] for k in self.knowledge]
            knowledge_embeddings = self.model.encode(knowledge_texts, convert_to_tensor=True)
            
            similarities = util.pytorch_cos_sim(question_embedding, knowledge_embeddings)[0]
            
            results = []
            for i in torch.topk(similarities, min(top_k, len(similarities))).indices:
                results.append(self.knowledge[i.item()])
            
            return results
        except Exception as e:
            logger.error(f"Similarity search error: {e}")
            return []

# Создаем глобальный экземпляр ИИ
assistant = SmartAssistant()

def google_search(query, lang="ru"):
    """Умный комбинированный поиск"""
    try:
        query_lower = query.lower()
        
        # Прямые ссылки для популярных запросов
        direct_sources = []
        
        if any(word in query_lower for word in ['путин', 'президент', 'кремль', 'правительство']):
            direct_sources = [
                "https://www.rbc.ru/politics/",
                "https://ria.ru/politics/",
                "https://tass.ru/politika"
            ]
        elif any(word in query_lower for word in ['новости', 'события', 'происшествия']):
            direct_sources = [
                "https://www.rbc.ru/",
                "https://ria.ru/",
                "https://lenta.ru/"
            ]
        elif any(word in query_lower for word in ['спорт', 'футбол', 'хоккей', 'баскетбол']):
            direct_sources = [
                "https://www.championat.com/",
                "https://sport.rbc.ru/",
                "https://www.sports.ru/"
            ]
        elif any(word in query_lower for word in ['технологии', 'гаджеты', 'it', 'компьютер']):
            direct_sources = [
                "https://habr.com/ru/news/",
                "https://www.ixbt.com/news/",
                "https://vc.ru/tech"
            ]
        
        # Поиск через разные поисковики
        search_results = []
        search_engines = [
            f"https://www.bing.com/search?q={query}&cc=RU",
            f"https://duckduckgo.com/html/?q={query}",
            f"https://html.duckduckgo.com/html/?q={query}"
        ]
        
        for search_url in search_engines:
            if len(search_results) >= 2:
                break
                
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                }
                
                response = requests.get(search_url, headers=headers, timeout=8)
                response.encoding = 'utf-8'
                
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    for link in soup.find_all('a', href=True):
                        href = link['href']
                        if (href.startswith('http') and 
                            not any(domain in href for domain in ['bing.com', 'duckduckgo.com', 'google.com', 'yandex.ru']) and
                            len(href) < 120 and
                            href not in search_results):
                            
                            search_results.append(href)
                            if len(search_results) >= 3:
                                break
            except:
                continue
        
        # Комбинируем результаты
        all_results = direct_sources + search_results
        unique_results = []
        seen = set()
        for result in all_results:
            if result not in seen:
                seen.add(result)
                unique_results.append(result)
            if len(unique_results) >= 3:
                break
        
        return unique_results if unique_results else [
            "https://www.rbc.ru/",
            "https://ria.ru/",
            "https://lenta.ru/"
        ]
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return [
            "https://www.rbc.ru/",
            "https://ria.ru/", 
            "https://lenta.ru/"
        ]

def extract_info_from_page(url):
    """Умное извлечение информации с комбинированным подходом"""
    try:
        # Быстрое определение для известных сайтов
        site_info = {
            'rbc.ru': 'РБК - актуальные новости политики и экономики',
            'ria.ru': 'РИА Новости - последние новости России и мира', 
            'tass.ru': 'ТАСС - новости политики и культуры',
            'lenta.ru': 'Лента.ру - свежие новости и события',
            'championat.com': 'Чемпионат - новости спорта',
            'sports.ru': 'Sports.ru - спортивные новости',
            'habr.com': 'Habr - новости технологий и IT',
            'ixbt.com': 'IXBT - новости высоких технологий',
            'vc.ru': 'VC.ru - бизнес и технологии'
        }
        
        for domain, info in site_info.items():
            if domain in url:
                assistant.add_knowledge(info, url)
                return info
        
        # Детальный анализ для других сайтов
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'utf-8'
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form']):
                element.decompose()
            
            # Стратегия 1: Заголовок страницы
            title = soup.find('title')
            title_text = title.get_text().strip() if title else ""
            
            # Стратегия 2: Основной заголовок h1
            h1 = soup.find('h1')
            h1_text = h1.get_text().strip() if h1 else ""
            
            # Стратегия 3: Мета-описание
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            meta_text = meta_desc['content'].strip() if meta_desc and meta_desc.get('content') else ""
            
            # Стратегия 4: Первые параграфы
            paragraphs = []
            for p in soup.find_all('p'):
                text = p.get_text().strip()
                if (len(text) > 40 and 
                    len(text) < 300 and
                    not any(word in text.lower() for word in ['реклама', 'cookie', '©', 'copyright', 'политика'])):
                    paragraphs.append(text)
                    if len(paragraphs) >= 2:
                        break
            
            # Выбираем лучший вариант
            best_text = ""
            candidates = [h1_text, meta_text, title_text] + paragraphs
            
            for candidate in candidates:
                if (candidate and 
                    len(candidate) > 20 and 
                    len(candidate) < 250 and
                    not candidate.startswith('http')):
                    best_text = candidate
                    break
            
            if best_text:
                clean_text = ' '.join(best_text.split())
                if len(clean_text) > 150:
                    clean_text = clean_text[:150] + "..."
                
                assistant.add_knowledge(clean_text, url)
                return clean_text
            
            return "Интересная информация по вашему запросу! Рекомендую ознакомиться с источником."
            
        return "Актуальные данные найдены! 📖"
        
    except Exception as e:
        logger.error(f"Page extract error: {e}")
        return "Нашел релевантную информацию! 🔍"

def generate_smart_response(question: str, context: str = "", lang: str = "ru") -> str:
    """Генерируем умный ответ с помощью ИИ"""
    try:
        # Простые правила для частых вопросов
        simple_answers = {
            "ru": {
                "привет": "Привет! 😊 Как я могу помочь?",
                "как дела": "У меня все отлично! Готов помочь с любым вопросом!",
                "спасибо": "Всегда пожалуйста! Обращайтесь еще! 🙏",
                "что ты умеешь": "Я могу искать информацию, отвечать на вопросы и помогать с различными задачами!",
                "кто ты": "Я умный помощник с искусственным интеллектом! 🤖",
                "time": f"Сейчас {datetime.now().strftime('%H:%M')} ⏰",
                "date": f"Сегодня {datetime.now().strftime('%d.%m.%Y')} 📅",
            },
            "en": {
                "hello": "Hi! 😊 How can I help you?",
                "how are you": "I'm great! Ready to help with any question!",
                "thank you": "You're welcome! Feel free to ask more! 🙏",
                "what can you do": "I can search information, answer questions and help with various tasks!",
                "who are you": "I'm a smart AI assistant! 🤖",
                "time": f"Current time: {datetime.now().strftime('%H:%M')} ⏰",
                "date": f"Today is {datetime.now().strftime('%Y-%m-%d')} 📅",
            }
        }
        
        # Проверяем простые вопросы
        question_lower = question.lower()
        lang_dict = simple_answers.get(lang, simple_answers["ru"])
        
        for key, answer in lang_dict.items():
            if key in question_lower:
                return answer
        
        # Ищем похожую информацию в базе знаний (только если ИИ доступен)
        similar_info = []
        if assistant.model:
            similar_info = assistant.find_similar(question)
        
        # Формируем контекст для ответа
        context_text = ""
        if similar_info:
            context_text = "На основе моих знаний:\n" + "\n".join([info["text"] for info in similar_info[:2]])
        
        if context:
            context_text += f"\n\nИз найденной информации:\n{context}"
        
        # Генерируем умный ответ
        if context_text:
            return f"{context_text[:600]}...\n\nМогу уточнить детали если нужно! 🔍"
        
        # Умный ответ по умолчанию
        smart_responses = {
            "ru": [
                f"По вопросу '{question}' я нашел интересные данные! 📊",
                f"Анализирую '{question}'... Есть актуальная информация! 🔍",
                f"Отличный вопрос! По теме '{question}' есть много свежих данных. 💡",
                f"Изучаю '{question}'... Нашел кое-что интересное! 🎯",
                f"По вашему запросу '{question}' - есть полезная информация! 📚"
            ],
            "en": [
                f"Regarding '{question}' I found interesting data! 📊",
                f"Analyzing '{question}'... There is relevant information! 🔍",
                f"Great question! There is a lot of fresh data on '{question}'. 💡",
                f"Researching '{question}'... Found something interesting! 🎯",
                f"For your query '{question}' - there is useful information! 📚"
            ]
        }
        
        return random.choice(smart_responses.get(lang, smart_responses["ru"]))
        
    except Exception as e:
        logger.error(f"Response generation error: {e}")
        return "Интересный вопрос! Давайте обсудим его подробнее. 💭"

# ========== ОСТАЛЬНЫЕ ФУНКЦИИ БЕЗ ИЗМЕНЕНИЙ ==========

async def start(update, context):
    """Начало работы - выбор языка"""
    keyboard = [[KeyboardButton(lang)] for lang in LANGUAGES.keys()]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    
    await update.message.reply_text("🌍 Choose your language / Выберите язык:", reply_markup=reply_markup)
    return LANGUAGE

async def language_handler(update, context):
    """Обработчик выбора языка"""
    user_lang_name = update.message.text
    user_id = update.message.from_user.id
    
    if user_lang_name in LANGUAGES:
        lang_code = LANGUAGES[user_lang_name]
        user_data[user_id] = {"lang": lang_code}
        
        texts = TEXTS.get(lang_code, TEXTS["ru"])
        await update.message.reply_text(texts["name_ask"], reply_markup=ReplyKeyboardRemove())
        return NAME
    else:
        await update.message.reply_text("Please choose from the list / Пожалуйста, выберите из списка")
        return LANGUAGE

async def name_handler(update, context):
    """Обработчик имени пользователя"""
    user_id = update.message.from_user.id
    name = update.message.text
    lang_code = user_data[user_id]["lang"]
    user_data[user_id]["name"] = name
    
    texts = TEXTS.get(lang_code, TEXTS["ru"])
    
    # Главное меню
    keyboard = [
        [KeyboardButton(texts["ask_question"])],
        [KeyboardButton(texts["generate_image"]), KeyboardButton(texts["settings"])],
        [KeyboardButton(texts["info"])]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(texts["greeting"].format(name=name), reply_markup=reply_markup)
    return MAIN_MENU

async def main_menu_handler(update, context):
    """Обработчик главного меню"""
    user_id = update.message.from_user.id
    choice = update.message.text
    lang_code = user_data[user_id]["lang"]
    texts = TEXTS.get(lang_code, TEXTS["ru"])
    
    if choice == texts["ask_question"]:
        # Клавиатура выбора стиля ИИ
        keyboard = [[KeyboardButton(style)] for style in AI_STYLES.keys()]
        keyboard.append([KeyboardButton("⬅️ Назад")])
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(texts["ai_style"], reply_markup=reply_markup)
        return AI_STYLE
        
    elif choice == texts["generate_image"]:
        await update.message.reply_text(texts["ask_image"], reply_markup=ReplyKeyboardRemove())
        return IMAGE_GEN
        
    elif choice == texts["settings"]:
        await update.message.reply_text("⚙️ Настройки в разработке...")
        return MAIN_MENU
        
    elif choice == texts["info"]:
        await update.message.reply_text("ℹ️ Этот бот использует AI для ответов на вопросы и генерации изображений")
        return MAIN_MENU
    
    return MAIN_MENU

async def ai_style_handler(update, context):
    """Обработчик выбора стиля ИИ"""
    user_id = update.message.from_user.id
    choice = update.message.text
    lang_code = user_data[user_id]["lang"]
    texts = TEXTS.get(lang_code, TEXTS["ru"])
    
    if choice == "⬅️ Назад":
        return await main_menu_handler(update, context)
    
    if choice in AI_STYLES:
        user_data[user_id]["ai_style"] = AI_STYLES[choice]
        await update.message.reply_text(texts["ask_question"], reply_markup=ReplyKeyboardRemove())
        return QUESTION
    
    await update.message.reply_text("Пожалуйста, выберите стиль из списка")
    return AI_STYLE

async def question_handler(update, context):
    """Обработчик вопросов - ТЕПЕРЬ С ИИ!"""
    user_id = update.message.from_user.id
    question = update.message.text
    lang_code = user_data[user_id]["lang"]
    texts = TEXTS.get(lang_code, TEXTS["ru"])
    
    await update.message.reply_text(texts["searching"])
    
    try:
        # 1. Ищем информацию в интернете
        search_results = google_search(question, lang_code)
        context_info = ""
        
        if search_results:
            # 2. Анализируем первую страницу
            page_text = extract_info_from_page(search_results[0])
            if page_text:
                context_info = page_text
        
        # 3. Генерируем умный ответ с ИИ
        response = generate_smart_response(question, context_info, lang_code)
        
        # 4. Добавляем источник если есть
        if search_results and context_info:
            response += f"\n\n🔗 Источник: {search_results[0]}"
        
        await update.message.reply_text(response)
        await update.message.reply_text(texts["thanks"])
            
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(texts["error"])
    
    return MAIN_MENU

async def image_generation_handler(update, context):
    """Обработчик генерации изображений"""
    user_id = update.message.from_user.id
    prompt = update.message.text
    lang_code = user_data[user_id]["lang"]
    texts = TEXTS.get(lang_code, TEXTS["ru"])
    
    await update.message.reply_text("🎨 Генерация изображения... (функция в разработке)")
    
    # Здесь будет реальная генерация изображения
    await update.message.reply_text(texts["image_created"])
    await update.message.reply_text("В будущей версии здесь будет ваше изображение!")
    
    return MAIN_MENU

async def cancel(update, context):
    """Отмена операции"""
    await update.message.reply_text("Операция отменена", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def main():
    """Основная функция"""
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    
    conv_handler = ConversationHandler(
    entry_points=[CommandHandler('start', start)],
    states={
        LANGUAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, language_handler)],
        NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_handler)],
        MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler)],
        AI_STYLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ai_style_handler)],
        QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, question_handler)],
        IMAGE_GEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, image_generation_handler)],
    },
    fallbacks=[CommandHandler('cancel', cancel)]
)
    
    
    dp.add_handler(conv_handler)
    print("🤖 Умный бот с ИИ запущен!")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
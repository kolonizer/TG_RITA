import os
import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Tuple

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties

from aiogram.types import InputMediaPhoto
# ================= НАСТРОЙКИ =================

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Put it in .env or environment variables.")
ADMIN_IDS = [313372023, 893519113]  # добавь сюда нужные ID

DB_PATH = "bot.sqlite3"

VIDEO_ENABLED = True
VIDEO_FILE_ID = "BAACAgIAAxkBAAIBnWmlig1rlhpT9x6c0xGlwdKasMIyAAIxkwACb24RSVk0ks25wXd2OgQ"

TEST_MODE = True
TEST_DELAY_SECONDS = 10  # 1 минута на шаг (для теста)

DISCOUNT_PRICE = 2030
FULL_PRICE = 2900

STEP2_PHOTOS = [
    "AgACAgIAAxkBAAOdaaAKHS1q1EwOTzO1p3op9dHuw2UAAg0TaxtizAABSYD8AxiJxqOYAQADAgADeQADOgQ",
    "AgACAgIAAxkBAAOeaaAKHRUMjz4WNmv8Fc-_TuZlR0wAAg4TaxtizAABSZ34k_vVUcXeAQADAgADeQADOgQ",
    "AgACAgIAAxkBAAOfaaAKHVA84zoFHezf2VnPYjYAARaOAAIPE2sbYswAAUn320evXjxLhwEAAwIAA3kAAzoE",
    "AgACAgIAAxkBAAOgaaAKHbu9fdKiiwrgBUrB9LG53swAAhATaxtizAABSWmna_Nyt5EvAQADAgADeQADOgQ",
    "AgACAgIAAxkBAAOhaaAKHfFPylXzsFcDRsTo8xkz8QgAAhETaxtizAABSQoJr8-B3wSxAQADAgADeQADOgQ",
    "AgACAgIAAxkBAAOiaaAKHa9-HQnLfWRoEL38bLEvCvkAAhITaxtizAABSTwW63TvSTRgAQADAgADeQADOgQ",
    "AgACAgIAAxkBAAOjaaAKHYyK9cy0RQo3jKNzo2bPyawAAhMTaxtizAABSbxdOqGgFvjIAQADAgADeQADOgQ",
    "AgACAgIAAxkBAAOkaaAKHVKXv5qW32WTgl3lxrS0UJMAAhQTaxtizAABSbni7Sdkst3HAQADAgADeQADOgQ",
]

DETAILS_TEXT = (
    """<b>ЧТО ТАКОЕ ПРОЕКТ «КАК НАЙТИ СВОЁ ПРЕДНАЗНАЧЕНИЕ»?</b>

Я создала этот курс для тех, кто потерял себя, и для тех, кто до сих пор не знает, кем хочет быть, когда вырастет 🥺

Если вы:

— <i>задаётесь вопросом о смысле жизни [своей жизни]</i>
— <i>не знаете, чем хотели бы заниматься и что сделает вас счастливыми</i>
— <i>не хотите прожить всю жизнь в вечных поисках,</i>

Я хочу вам помочь! 🫂

На проекте вы не просто поймёте, какая профессия вам подходит.
<b>Это будет ГЛУБИННАЯ РАБОТА, благодаря которой вы:</b>

• <i>научитесь понимать и слышать себя</i>
• <i>выстраивать более здоровые отношения с собой и окружающими</i>
• <i>сможете хорошо узнать себя и познакомиться со своими убеждениями, ценностями, мечтами</i>
• <i>вы научитесь планировать свою жизнь так, чтобы каждое действие вело вас к исполнению мечты и реализации предназначения</i>

📌 <b>Курс будет в формате закрытого телеграм-канала:</b>
каждый день вам будут приходить различные задания и практики, на которые нужно будет выделять <b>от 5 до 60 минут в день</b>.

Также у нас будет <b>общий чат</b> со всеми участниками, где мы будем делиться своими достижениями и трудностями, поддерживать друг друга.
<b>Я тоже всегда буду на связи</b>, чтобы помочь или ответить на вопрос! 🤲🏻

<i>Никаких скучных лекций и нравоучений, только практика, которая поможет вам по-настоящему найти себя</i> ❤️‍🔥

На фото ты можешь <b>изучить</b> подробное наполнение 24 дней курса, а волшебная кнопочка ниже перенаправит тебя на путь исследования своей миссии 👇🏻"""
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

def delay(minutes: int = 0, hours: int = 0) -> int:
    if TEST_MODE:
        return TEST_DELAY_SECONDS
    return minutes * 60 + hours * 3600

# ============================================

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()

# ================= ТЕКСТЫ =================

text_1 = "Привет! На связи риталпиаш💛\n\nОтправляю тебе <b>видео-урок «Как найти своё предназначение?»</b>, хорошего просмотра! <i> \n\nP.s. Эти 30 минут могут изменить твою жизнь</i>👀"

text_2 = "Ну как ты после просмотра?\n\nЕсли понимаешь, что тема тебе близка и хочется глубже в неё погрузиться, вместе поработать над пониманием себя: своих желаний, эмоций, потребностей, мечт и целей, приглашаю тебя присоединиться к <b>полному курсу</b> «Как найти своё предназначение?»❤️‍🩹\n\n📌Длительность курса - <b>25 дней</b>, каждый из которых будет посвящен определенной теме <i>(наполнение курса ты можешь подробно прочитать на фото). </i><b>90% курса - практика</b>, и только минимум теории. Я специально подобрала различные техники, упражнения, медитации, практики и задания, с помощью которых ты сможешь <i>не просто понять</i> что-то на уровне мыслей и чувств, но и <i>закрепить все инсайты действиями</i>, ведь только наши поступки способны действительно изменить жизнь.\n\nКурс стартует 30 марта, успевайте занять место! <i>(Да, их количество ограничено, так как я самостоятельно буду со всеми общаться и отвечать каждому)</i>\n\nСпециально для вас я даю <b>скидку 30% ровно на час</b> после отправки этого сообщения! В течение этого часа вы можете приобрести курс за <b>2030</b> рублей вместо 2900🤯 <i>(Больше такой скидки не будет! А ограничение час - чтобы вы не тянули</i>😋<i>) </i>"

text_3 = "У вас бывало такое, что вроде <b>головой всё понимаешь</b>, но всё равно остается вопрос «<b>А делать-то что?</b>»\n\nТакое часто бывает при прослушивании всяких подкастов, лекций, интервью и тд. Люди делятся важными мыслями и знаниями, но без практики в вашей жизни ничего не изменится от этих ✨<b>инсайтов</b>✨\n\nИменно поэтому 90% моего курса по предназначению состоит из <b>практики</b>. Я не просто расскажу вам, как найти своё предназначение. Я помогу вам сделать это. Это не лекции, это <b>ежедневные задания</b> и практики, с помощью которых ты наконец сможешь понять, что тебе делать. <i>Тебе необязательно знать теорию, важнее - добиться желаемых изменений</i>😼\n\nКурс полностью сделан <b>вручную</b> мной, на основе моих знаний по психологии и жизненного опыта. Я добавила только те практики, которые <b>помогли мне самой</b>. Ни на одном этапе я не использовала ИИ (чатик джипити вы и сами можете открыть бесплатно). Мне было важно вложить свою энергию в этот продукт.\n\nОн точно вам поможет, ведь курс «Как найти своё предназначение?» - буквально <b>реализация моего предназначения</b>. <i>Для меня это очень символично</i>🥹"

text_4 = "<b>В ЧЁМ СМЫСЛ ЖИЗНИ?</b>\n\nВы когда-нибудь задумывались над этим вопросом? Если поиск ответа для вас до сих пор актуален, рекомендую дочитать до конца!👇🏻\n\nПредлагаю взглянуть на этот вопрос под другим углом. <b>Что, если нам не нужно отвечать на него?</b> Что если <b>НЕ МЫ</b> задаем жизни вопрос «<b>в чём твой смысл?</b>», а <b>ЖИЗНЬ НАМ?</b>\n\nЕжедневно, сталкивая нас с различными трудностями, жизнь спрашивает у нас «<i>А в чём твой смысл?</i>». А наша задача - <b>своими поступками</b> ответить на этот вопрос. В таком случае нам не нужно искать смысл в жизни. Нам важно <b>увидеть его в себе</b>❤️\n\n<b>ВАШ СМЫСЛ</b> - это пересечение ваших ценностей в данный момент времени. Получается, важно просто понять свои ценности и начать их реализовывать в каждом дне?\n\nЕсли вам откликается такой подход, приглашаю вас <b>вместе поисследовать свой смысл</b> на моём авторском курсе «Как найти своё предназначение?»⬇️"

text_5 = "<b>ВАМ ТОЧНО ЭТО НАДО, ЕСЛИ…</b>\n\n💛Вы учитесь <b>в школе</b>, подходит время принимать решение, <b>куда же поступить</b>, но вы в растерянности и совсем не знаете, что выбрать. Возможно, вам интересно много сфер, а возможно, наоборот, будто не интересует ничего…А может, вы боитесь, что интересующая вас сфера не принесет желаемый доход и поэтому сомневаетесь в выборе?\n\n💛Вы <b>уже поступили</b>, но столкнулись с ощущением «<i>кажется, это не моё…</i>». И вот возникает вопрос «<i>Что делать дальше?</i>».\n\nПредставляете, есть даже термин - <b>кризис 2 курса</b>: с момента выбора будущей профессии вы выросли, ваши взгляды на жизнь поменялись и теперь вы в сомнениях: куда ли я пошла? Отчислиться или доучиться? <i>Что делать после окончания учебы?</i>\n\n💛Вы <b>уже закончили</b> учебное заведение, но что делать дальше – загадка. Вы точно знаете, что ваша профессия вам не нравится, но что нравится – не понимаете. С одной стороны – хочется зарабатывать деньги, с другой – не хочется всю жизнь горбатиться на нелюбимой работе.\n\nМне до безумия знакомы все эти чувства, и я хочу помочь вам справиться с этим. Поэтому приглашаю на курс «Как найти своё предназначение?»\n<i>(90% практики и только 10% теории)</i>\n\n<b>КАКОЙ РЕЗУЛЬТАТ ВЫ ПОЛУЧИТЕ</b>👇🏻\n\nВы научитесь <b>понимать себя</b>, свои желания, эмоции, потребности, ценности. Научитесь выстраивать более гармоничные <b>отношения</b> с окружающими, близкими. Это всё, в конечном итоге, поможет вам <b>найти себя</b>. Вы получите большое количество инструментов, которые помогут вам понять своё предназначение и <b>чётко сформулировать свою миссию в жизни</b>. Вы научитесь <b>планировать свою жизнь</b> так, чтобы каждый день приближал вас к исполнению мечты и реализации предназначения. Дни наконец перестанут быть бессмысленными, серыми и однообразными. Вы наконец сможете <b>избавиться от постоянных метаний</b>, непонятного, всепоглощающего чувства «<i>я не знаю, чего я хочу от жизни</i>». Вы найдёте для себя свой смысл жизни. И поймёте, как его воплотить.\n\n<i>Но всё зависит и от ваших стараний тоже ;)</i>"

text_6 = "<b>А ВДРУГ У МЕНЯ НЕ ПОЛУЧИТСЯ?</b>\n\nВам знакомо это опасение?\n<i>«Вдруг я куплю курс, потрачу время, силы, деньги, а результата не будет…?»</i>🥺\n\nЗнаете, <b>результат - это относительное понятие.</b> Как вы поймёте, получили ли вы результат? Если вы просто теоретически поймёте своё предназначение? Или если ваша жизнь перевернётся на 180 градусов и вы станете другим человеком? Если смените работу и пойдёте пробовать новое? Или если просто начнёте чуть лучше понимать себя, слышать свои желания?\n\n<b>Поиск своего предназначения - это процесс.</b> И сделав шаг в его сторону, вы в любом случае запустите этот процесс. Я дам вам все инструменты, а дальше всё будет зависеть от вас🤲🏻\n\nА не попробовав, вы даже не узнаете, ответ на вопрос в начале этого сообщения :)"

text_7 = "<b>Когда человек занимается тем, что ему нравится, успех приходит сам.</b> Когда мы играем чужие роли, мы всегда будем неуспешны.\n\nПоверьте, я знаю, о чём говорю, ведь в своей жизни я была и почтальоном, и няней, и официанткой, и SMM, и безработной. Я поступала, казалось, в ВУЗ мечты, а потом розовые очки с треском разбивались. И в этом треске было слышно тихое «<i>Похоже, это не моё…</i>». А потом тишина и непонимание, куда идти дальше😔\n\nМне казалось, что если стараться, работать без выходных, идти к своим целям, то успех придет. Но только я забыла узнать, какие цели были действительно мои. И только когда я перестала бежать, остановилась и спросила себя «<i>а чего я действительно хочу?</i>», «<i>а ведут ли мои действия меня к моим мечтам?</i>», тогда я всё поняла…\n\nОказалось, можно было работать в своё <b>удовольствие</b> и позволять себе отдыхать. Достаточно просто <b>делать то, что действительно любишь</b>, и успех начнёт приходить без переработок. Раз - и первый миллион просмотров. Одно видео - а у меня уже 200+ заявок на консультации. Я думала, так не бывает💔\n\n<b>Вспомните сейчас свою жизнь.</b> Были ли у вас ситуации, когда казалось, что как бы ты ни старался, ничего не получается? А ситуации, где всё будто складывалось само собой? Думаете, это просто совпадения?"

text_8 = "<b>КАК СПРАВИТЬСЯ СО СТРАХОМ?</b>\n\nВсе эмоции, которые мы испытываем, являются <b>полезными сигналами</b>. Природа создала их не для того, чтобы испортить нам жизнь. У каждой эмоции есть своя <b>функция</b>✨\n\nСтрах даёт нам <b>энергию для ухода от опасности.</b> Он заложен в нашей психике, чтобы увидев медведя в кустах, мы спрятались или убежали, тем самым спасли свою жизнь.\n\nНо сейчас в нашем мире такое количество стимулов, что мы можем начать бояться всего, без разбора, что представляет реальную опасность, а что нет. Так появляется тревожность - постоянный страх о чисто теоретическом будущем. Такая эмоция может привести к отказу от многих возможностей😔\n\n<i>Боюсь, что ничего не получится // что потеряю время → вообще не буду пробовать</i>\n\nСтрах – еще и самая опасная эмоция, которая оказывает <b>влияние на наше сознание и поведение.</b> Он может буквально блокировать нас и наше развитие. Вот что действительно страшно😡\n\nТак что же делать?\nПризнайте свой страх, заметьте его, дайте ему место. Вам можно бояться.\nТеперь страх не управляет вами. Как только вы осознаете его, у вас появляется прекрасная возможность – выбирать: «<i>Да, я боюсь, но не смотря на это я могу идти за своими желаниями</i>»\n\n<i>Я живу всю осознанную жизнь с девизом «Бойся, но делай».</i> И он помог мне добиться того, что я имею.\n\nЕсли чувствуешь, что готов(а) попробовать искать себя, несмотря на страх, жми на кнопочку ниже 👇🏻"

text_9 = "<b>КАЖЕТСЯ, ЭТО НЕ МОЁ…</b>👀\n\nИ в этот момент весь фундамент, который ты так долго выстраивал, будто рушится под ногами. Как то, над чем я так старательно работала, может оказаться не моим?\n\nТы просто однажды просыпаешься с мыслью «<i>Я не хочу дальше жить ТАК.</i>». И что теперь делать с этой мыслью? Может забыть, отмахнуться, сделать вид, что не заметил её, и просто жить как раньше? Но как раньше уже не получится, ведь с каждым днём эта мысль будет всё громче кричать тебе «<i>пора что-то менять!</i>»😭\n\nИменно это я пережила, когда осознала, что место, в котором я проучилась 2 года (а до этого ещё потратила огромное количество усилий, чтобы поступить на бюджет) – не моё.\n\nКартина маслом: я сижу на паре и мысль, которую я неделями подавляла, не выдерживает и начинает неистово кричать в голове:\n• «Я не хочу здесь быть»\n• «Я не на своём месте»\n• «Я не должна быть тут»\n\nНа глазах наворачиваются слёзы, я убегаю в туалет и остаюсь наедине с желанием прямо сейчас забрать документы и не возвращаться никогда.\nЭто была моя последняя пара в НГУ.\n\nНо настоящий ад начался потом. Когда пришлось сказать маме, а потом и всем остальным. На протяжении года я ежедневно выслушивала от огромного количества людей осуждение и попытки переубедить. Мне даже говорили, что я не смогу построить с Колей семью из-за того, что у нас будут разные взгляды (ведь он закончил НГУ, а я нет)\n\nНо я не послушала никого, кроме себя, ведь с каждым днём убеждалась, что делаю всё правильно (хотя откаты тоже были). И теперь безумно благодарна себе, ведь всё сложилось наилучшим образом! А стоило лишь понять себя🤍\n\nЕсли тебе знакомы такие переживания, ещё <b>можно присоединиться</b> к моему проекту «Как найти своё предназначение?», пока осталось <b>несколько свободных мест!</b> Там я на протяжении <b>25 дней</b> буду помогать вам найти себя с помощью различных практик и знаний, которые в своё время помогли мне⬇️"

text_10 = "<b>ЧТО ПОМОГЛО МНЕ НАЙТИ СЕБЯ?</b>\n\nВ какой-то момент я осознала, что постоянно мыслю категориями НАДО:\n«Надо выпить кофе»\n«Надо приготовить ужин»\n«Надо надеть эту кофточку, давно её не носила»\n\nА это только мелочи. Представляете, что было, когда дело касалось работы, учёбы и тд?🤦🏻‍♀️\n\nВместо того, чтобы задуматься, чего я хочу (банально съесть на завтрак кашу или яичницу), я только диктовала себе, что нужно делать.\n\nЭто осознание настолько поразило меня, что из глаз потекли слёзы…Как же я, будучи такой ✨осознанной, проработанной и вообще самой умной✨ настолько сильно разучилась чувствовать свои желания?\n\n<i>В этот момент Коля спросил у меня:</i>\n- А чего хочешь прямо сейчас?\n- Гулять, - ответила я.\n- Пойдём!🫶🏻\n\nВ этот момент я совсем разрыдалась от удивления, что можно вот так просто забить на то, что НАДО ложиться спать (был уже час ночи), и вообще он же не любит гулять в холодную погоду…Оказалось, можно просто заглянуть внутрь себя и позволить хотя бы на секунду задуматься, чего я сейчас хочу. И просто пойти гулять.\n\nЯ нашла для себя простое решение: <b>НАЧАТЬ ЧУВСТВОВАТЬ СВОИ «ХОЧУ»</b>🤍\n\nРегулярно на протяжении дня спрашивать у себя:\n«Чем я хочу позавтракать?»\n«Что я хочу надеть?»\n«Чем я хочу сейчас заняться?» и тд\n\nВажно было научиться ХОТЕТЬ что-то делать, так как дофамин вырабатывается при достижении цели, основанной на наших желаниях.\nВысокий дофамин = 📈 энергии и сил → успеваешь больше\n\nПоэтому важно создавать себе дофаминовые «хочу»\n\n<b>Дофаминовая цепочка</b> выглядит так: <b>хочу - делаю - получаю - радуюсь</b>\n\n<i>Так можно и счастливыми стать🥹</i>\nТы со мной?"

# ================= КНОПКИ =================

def kb_action(label: str, cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=cb)]
    ])

def kb_details_and_go(details_label: str, go_label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=details_label, callback_data="details")],
        [InlineKeyboardButton(text=go_label, callback_data="pay")]
    ])

def kb_pay_with_receipt(price: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ОТПРАВИТЬ ЧЕК", callback_data="send_receipt")]
    ])

def kb_details_go_only() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Я ИДУ!", callback_data="pay")]
    ])

# ================= SQLite =================

_db_lock = asyncio.Lock()
_conn: Optional[sqlite3.Connection] = None

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def dt_to_ts(dt: datetime) -> int:
    return int(dt.timestamp())

async def db_init():
    global _conn
    _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    _conn.execute("PRAGMA journal_mode=WAL;")
    _conn.execute("PRAGMA synchronous=NORMAL;")

    _conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        started_at INTEGER,
        paid INTEGER DEFAULT 0,
        discount_until INTEGER,
        awaiting_receipt INTEGER DEFAULT 0
    );
    """)

    _conn.execute("""
    CREATE TABLE IF NOT EXISTS queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        step INTEGER NOT NULL,
        run_at INTEGER NOT NULL,
        sent_at INTEGER,
        UNIQUE(user_id, step),
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    );
    """)

    # На всякий — мягкая миграция, если БД уже существовала
    await _ensure_column("users", "discount_until", "INTEGER")
    await _ensure_column("users", "awaiting_receipt", "INTEGER DEFAULT 0")
    await _ensure_column("users", "paid", "INTEGER DEFAULT 0")

    _conn.commit()

    # 👇 удаляем шаг 99 из очереди для всех (чтобы он не улетел после рестарта)
    await db_exec("DELETE FROM queue WHERE step=99")

async def _ensure_column(table: str, col: str, coltype: str):
    # sqlite pragma table_info
    async with _db_lock:
        cols = [r[1] for r in _conn.execute(f"PRAGMA table_info({table});").fetchall()]
        if col not in cols:
            _conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype};")
            _conn.commit()

async def db_exec(sql: str, params=()):
    async with _db_lock:
        cur = _conn.execute(sql, params)
        _conn.commit()
        return cur

async def db_fetchone(sql: str, params=()):
    async with _db_lock:
        cur = _conn.execute(sql, params)
        return cur.fetchone()

async def db_fetchall(sql: str, params=()):
    async with _db_lock:
        cur = _conn.execute(sql, params)
        return cur.fetchall()

# ================= ПЛАН ВОРОНКИ =================

def build_schedule(start_dt: datetime) -> List[Tuple[int, int, int]]:
    """
    Возвращает список (step, run_at_ts, discount_until_ts)
    discount_until_ts считается как (шаг2 + 1 час)
    """
    t0 = start_dt

    t2 = t0 + timedelta(seconds=delay(minutes=40))
    discount_until = t2 + timedelta(seconds=delay(hours=1))

    schedule = []
    schedule.append((2, dt_to_ts(t2), dt_to_ts(discount_until)))

    t3 = t2 + timedelta(seconds=delay(hours=24))
    schedule.append((3, dt_to_ts(t3), dt_to_ts(discount_until)))

    t4 = t3 + timedelta(seconds=delay(hours=48))
    schedule.append((4, dt_to_ts(t4), dt_to_ts(discount_until)))

    cur = t4
    for step in range(5, 11):
        cur = cur + timedelta(seconds=delay(hours=48))
        schedule.append((step, dt_to_ts(cur), dt_to_ts(discount_until)))

    return schedule

async def enqueue_user(user_id: int, username: Optional[str]):
    now = utcnow()
    now_ts = dt_to_ts(now)

    existing = await db_fetchone("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    schedule = build_schedule(now)
    _, _, discount_until_ts = schedule[0]

    if existing is None:
        await db_exec(
            "INSERT INTO users(user_id, username, started_at, paid, discount_until, awaiting_receipt) "
            "VALUES(?,?,?,0,?,0)",
            (user_id, username, now_ts, discount_until_ts)
        )
    else:
        await db_exec(
            "UPDATE users SET username=?, started_at=?, paid=0, discount_until=?, awaiting_receipt=0 "
            "WHERE user_id=?",
            (username, now_ts, discount_until_ts, user_id)
        )
        await db_exec("DELETE FROM queue WHERE user_id=?", (user_id,))

    for step, run_at, _ in schedule:
        await db_exec(
            "INSERT OR IGNORE INTO queue(user_id, step, run_at, sent_at) VALUES(?,?,?,NULL)",
            (user_id, step, run_at)
        )

async def reset_user_db(user_id: int):
    await db_exec("DELETE FROM queue WHERE user_id=?", (user_id,))
    await db_exec("DELETE FROM users WHERE user_id=?", (user_id,))

async def is_paid(user_id: int) -> bool:
    row = await db_fetchone("SELECT paid FROM users WHERE user_id=?", (user_id,))
    return bool(row and row[0] == 1)

async def already_started(user_id: int) -> bool:
    row = await db_fetchone("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    return row is not None

async def get_current_price(user_id: int) -> int:
    row = await db_fetchone("SELECT discount_until FROM users WHERE user_id=?", (user_id,))
    if not row or not row[0]:
        return FULL_PRICE
    discount_until = int(row[0])
    now_ts = dt_to_ts(utcnow())
    return DISCOUNT_PRICE if now_ts <= discount_until else FULL_PRICE

async def set_awaiting_receipt(user_id: int, value: int):
    await db_exec("UPDATE users SET awaiting_receipt=? WHERE user_id=?", (value, user_id))

async def is_awaiting_receipt(user_id: int) -> bool:
    row = await db_fetchone("SELECT awaiting_receipt FROM users WHERE user_id=?", (user_id,))
    return bool(row and int(row[0]) == 1)

async def confirm_purchase(user_id: int):
    # покупка считается совершенной только после чека
    await db_exec("UPDATE users SET paid=1, awaiting_receipt=0 WHERE user_id=?", (user_id,))
    # останавливаем воронку
    now_ts = dt_to_ts(utcnow())
    await db_exec("UPDATE queue SET sent_at=? WHERE user_id=? AND sent_at IS NULL", (now_ts, user_id))

# ================= ОТПРАВКА ПО ШАГУ =================

async def send_step(user_id: int, step: int):
    if await is_paid(user_id):
        return

    if step == 2:
        # 1) отправляем альбом фото
        media = [InputMediaPhoto(media=fid) for fid in STEP2_PHOTOS]
        await bot.send_media_group(chat_id=user_id, media=media)

        # 2) отправляем текст как раньше + кнопку
        await bot.send_message(
            chat_id=user_id,
            text=text_2,
            reply_markup=kb_action("купить", "pay")
        )
    elif step == 3:
        await bot.send_message(user_id, text_3, reply_markup=kb_action("ХОЧУ", "pay"))
    elif step == 4:
        await bot.send_message(user_id, text_4, reply_markup=kb_details_and_go("УЗНАТЬ ПОДРОБНОСТИ", "ПРИНЯТЬ УЧАСТИЕ"))
    elif step == 5:
        await bot.send_message(user_id, text_5, reply_markup=kb_details_and_go("УЗНАТЬ ПОДРОБНОСТИ", "ЗАПИСАТЬСЯ"))
    elif step == 6:
        await bot.send_message(user_id, text_6, reply_markup=kb_details_and_go("ПОДРОБНЕЕ", "Я ИДУ!"))
    elif step == 7:
        await bot.send_message(user_id, text_7, reply_markup=kb_action("ПОНЯТЬ, ЧЕМ ХОЧУ ЗАНИМАТЬСЯ", "pay"))
    elif step == 8:
        await bot.send_message(user_id, text_8, reply_markup=kb_details_and_go("РАССКАЖИ ПОДРОБНЕЕ", "УГОВОРИЛА"))
    elif step == 9:
        await bot.send_message(user_id, text_9, reply_markup=kb_action("ДЕЛАЕМ!", "pay"))
    elif step == 10:
        await bot.send_message(user_id, text_10, reply_markup=kb_action("ЛЕТС ГОУ", "pay"))

# ================= ВОРКЕР ОЧЕРЕДИ =================

async def queue_worker():
    logging.info("Queue worker started")
    while True:
        try:
            now_ts = dt_to_ts(utcnow())
            rows = await db_fetchall(
                "SELECT id, user_id, step FROM queue "
                "WHERE sent_at IS NULL AND run_at <= ? "
                "ORDER BY run_at ASC LIMIT 20",
                (now_ts,)
            )

            if not rows:
                await asyncio.sleep(1 if TEST_MODE else 3)
                continue

            for qid, user_id, step in rows:
                # пометим, чтобы избежать дублей при рестарте
                await db_exec("UPDATE queue SET sent_at=? WHERE id=?", (now_ts, qid))
                try:
                    await send_step(user_id, step)
                except Exception as e:
                    logging.error(f"Send step error user={user_id} step={step}: {e}")
                    # откат
                    await db_exec("UPDATE queue SET sent_at=NULL WHERE id=?", (qid,))

        except Exception as e:
            logging.error(f"Worker loop error: {e}")

        await asyncio.sleep(0)

# ================= PAY FLOW =================

def payment_message(price: int) -> str:

    if price == DISCOUNT_PRICE:
        price_text = f"<s>{FULL_PRICE} рублей</s> <b>{DISCOUNT_PRICE} рублей</b>"
    else:
        price_text = f"<b>{FULL_PRICE} рублей</b>"

    return (
        "Благодарю за доверие! Давай руку и пойдём вместе искать твоё предназначение 🫱🏻🫲🏻\n\n"
        f"Для оплаты места на курсе переведи {price_text} по реквизитам:\n\n"
        "<b>Номер телефона:</b> 89139034994\n"
        "<b>ИЛИ номер карты:</b> 2200011679704925\n"
        "Газпромбанк\n"
        "Получатель: Лобанова Маргарита Сергеевна\n\n"
        "После оплаты пришли чек сюда, я проверю его и добавлю тебя в чат курса✨"
    )
# ================= HANDLERS =================

@dp.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username

    if await already_started(user_id):
        await message.answer("Ты уже проходишь воронку 💛\nЕсли хочешь заново — напиши /reset")
        return

    # 1: сразу
    if VIDEO_ENABLED:
        await message.answer_video(video=VIDEO_FILE_ID, caption=text_1)
    else:
        await message.answer(text_1)

    await enqueue_user(user_id, username)
    logging.info(f"User enqueued {user_id} @{username}")

@dp.message(F.text == "/reset")
async def reset_cmd(message: Message):
    await reset_user_db(message.from_user.id)
    await message.answer("Ок 👌 Я забыл(а) тебя. Можешь снова нажать /start")

@dp.message(F.video)
async def get_video_id(message: Message):
    await message.answer(f"VIDEO_FILE_ID:\n<code>{message.video.file_id}</code>")


@dp.callback_query(F.data == "details")
async def details_cb(callback: CallbackQuery):
    user_id = callback.from_user.id

    # 1) альбом фото
    media = [InputMediaPhoto(media=fid) for fid in STEP2_PHOTOS]
    await bot.send_media_group(chat_id=user_id, media=media)

    # 2) текст + кнопка
    await callback.message.answer(
        DETAILS_TEXT,
        reply_markup=kb_action("КУДА ПЛАТИТЬ?", "pay")
    )

    await callback.answer()

@dp.callback_query(F.data == "pay")
async def pay_cb(callback: CallbackQuery):
    user_id = callback.from_user.id

    if await is_paid(user_id):
        await callback.message.answer("Ты уже отправил(а) чек ✅ Если что — напиши мне ещё раз 💛")
        await callback.answer()
        return

    price = await get_current_price(user_id)
    await callback.message.answer(payment_message(price), reply_markup=kb_pay_with_receipt(price))
    await callback.answer()

@dp.callback_query(F.data == "send_receipt")
async def send_receipt_cb(callback: CallbackQuery):
    user_id = callback.from_user.id

    if await is_paid(user_id):
        await callback.message.answer("Покупка уже подтверждена ✅")
        await callback.answer()
        return

    await set_awaiting_receipt(user_id, 1)
    await callback.message.answer("Отправь, пожалуйста, фото или файл чека сюда 👇")
    await callback.answer()

# 3) Принимаем чек только если нажата кнопка "ОТПРАВИТЬ ЧЕК"
@dp.message(F.photo)
async def receipt_photo(message: Message):
    user_id = message.from_user.id
    if not await is_awaiting_receipt(user_id):
        return

    price = await get_current_price(user_id)

    # берём самое большое фото
    photo = message.photo[-1].file_id

    caption = (
        f"✅ <b>ЧЕК ПОЛУЧЕН</b>\n"
        f"User: <b>{message.from_user.full_name}</b>\n"
        f"Username: @{message.from_user.username}\n"
        f"User ID: <code>{user_id}</code>\n"
        f"Сумма: <b>{price}₽</b>\n"
        f"Время (UTC): {utcnow().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(admin_id, photo=photo, caption=caption)
        except Exception as e:
            logging.warning(f"Не удалось отправить админу {admin_id}: {e}")
    await confirm_purchase(user_id)

    await message.answer("Спасибо! ✅ Чек получен. Я скоро подтвержу оплату 💛")

@dp.message(F.document)
async def receipt_document(message: Message):
    user_id = message.from_user.id
    if not await is_awaiting_receipt(user_id):
        return

    price = await get_current_price(user_id)
    doc_id = message.document.file_id

    caption = (
        f"✅ <b>ЧЕК ПОЛУЧЕН</b>\n"
        f"User: <b>{message.from_user.full_name}</b>\n"
        f"Username: @{message.from_user.username}\n"
        f"User ID: <code>{user_id}</code>\n"
        f"Сумма: <b>{price}₽</b>\n"
        f"Время (UTC): {utcnow().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_document(admin_id, document=doc_id, caption=caption)
        except Exception as e:
            logging.warning(f"Не удалось отправить админу {admin_id}: {e}")

    await confirm_purchase(user_id)

    await message.answer("Спасибо! ✅ Чек получен. Я скоро подтвержу оплату 💛")

# ================= ЗАПУСК =================

async def main():
    logging.info("Бот запущен 🚀")
    await db_init()
    asyncio.create_task(queue_worker())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
import os
import asyncio
import logging
import sqlite3
import re
from html import escape, unescape
from weakref import WeakValueDictionary
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Tuple

from bot_stats import init_stats, get_stats, reset_stats, format_stats
from bot_settings import init_settings, get_test_mode, set_test_mode
import bot_receipts as receipts

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.filters import CommandStart, Command
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InputMediaPhoto
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter, TelegramNetworkError
from aiohttp import ClientConnectorError

# ================= НАСТРОЙКИ =================

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Put it in .env or environment variables.")

ADMIN_IDS = [313372023, 893519113]
DB_PATH = os.getenv("DB_PATH", "bot.sqlite3")

VIDEO_ENABLED = True
VIDEO_FILE_ID = "BAACAgIAAxkBAAIBnWmlig1rlhpT9x6c0xGlwdKasMIyAAIxkwACb24RSVk0ks25wXd2OgQ"

TEST_MODE = os.getenv("TEST_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}
TEST_DELAY_SECONDS = 10
TEST_DISCOUNT_SECONDS = 60

DISCOUNT_PRICE = (2333, 3888)
FULL_PRICE = (3333, 5555)
DISCOUNT_SECONDS = 60 * 60
QUEUE_CONCURRENCY = 5
QUEUE_SEND_TIMEOUT = 30
QUEUE_RETRY_SECONDS = 30

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
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

def is_test_user(user_id: Optional[int]) -> bool:
    return TEST_MODE and user_id in ADMIN_IDS


def discount_duration(user_id: int) -> int:
    return TEST_DISCOUNT_SECONDS if is_test_user(user_id) else DISCOUNT_SECONDS


def delay(minutes: int = 0, hours: int = 0, user_id: Optional[int] = None) -> int:
    if is_test_user(user_id):
        return TEST_DELAY_SECONDS
    return minutes * 60 + hours * 3600


# ============================================

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()
_update_tasks = set()


@dp.update.outer_middleware()
async def track_update_task(handler, event, data):
    task = asyncio.current_task()
    _update_tasks.add(task)
    try:
        return await handler(event, data)
    finally:
        _update_tasks.discard(task)

# ================= ТЕКСТЫ =================

text_1 = "Привет! На связи риталпиаш💛\n\nОтправляю тебе <b>видео-урок «Как найти своё предназначение?»</b>, хорошего просмотра! <i> \n\nP.s. Эти 30 минут могут изменить твою жизнь</i>👀"

text_2 = 'Ну как ты после просмотра?\n\nЕсли понимаешь, что тема тебе близка и хочется глубже в неё погрузиться, вместе поработать над пониманием себя: своих желаний, эмоций, потребностей, мечт и целей, приглашаю тебя присоединиться к <b>полному курсу</b> «Как найти своё предназначение?»❤️\u200d🩹\n\n📌Длительность курса - <b>24 дня</b>, каждый из которых будет посвящен определенной теме <i>(наполнение курса ты можешь подробно прочитать на фото). </i><b>90% курса - практика</b>, и только минимум теории. Я специально подобрала различные техники, упражнения, медитации, практики и задания, с помощью которых ты сможешь <i>не просто понять</i> что-то на уровне мыслей и чувств, но и <i>закрепить все инсайты действиями</i>, ведь только наши поступки способны действительно изменить жизнь.\n\nКурс стартует 30 сентября, успевайте занять место! <i>(Да, их количество ограничено, так как я самостоятельно буду со всеми общаться и отвечать каждому)</i>\n\nСпециально для вас я даю <b>скидку 30% ровно на час</b> после отправки этого сообщения! В течение этого часа вы можете приобрести курс по одному из двух тарифов:\n1️⃣ С обратной связью от меня - <b>3 888 ₽</b> вместо 5 555 ₽\n2️⃣ Без обратной связи - <b>2 333 ₽</b> вместо 3 333 ₽🤯\n\n<i>(Больше такой скидки не будет! А ограничение час - чтобы вы не тянули</i>😋<i>) </i>'

text_3 = "У вас бывало такое, что вроде <b>головой всё понимаешь</b>, но всё равно остается вопрос «<b>А делать-то что?</b>»\n\nТакое часто бывает при прослушивании всяких подкастов, лекций, интервью и тд. Люди делятся важными мыслями и знаниями, но без практики в вашей жизни ничего не изменится от этих ✨<b>инсайтов</b>✨\n\nИменно поэтому 90% моего курса по предназначению состоит из <b>практики</b>. Я не просто расскажу вам, как найти своё предназначение. Я помогу вам сделать это. Это не лекции, это <b>ежедневные задания</b> и практики, с помощью которых ты наконец сможешь понять, что тебе делать. <i>Тебе необязательно знать теорию, важнее - добиться желаемых изменений</i>😼\n\nКурс полностью сделан <b>вручную</b> мной, на основе моих знаний по психологии и жизненного опыта. Я добавила только те практики, которые <b>помогли мне самой</b>. Ни на одном этапе я не использовала ИИ (чатик джипити вы и сами можете открыть бесплатно). Мне было важно вложить свою энергию в этот продукт.\n\nОн точно вам поможет, ведь курс «Как найти своё предназначение?» - буквально <b>реализация моего предназначения</b>. <i>Для меня это очень символично</i>🥹"

text_4 = "<b>В ЧЁМ СМЫСЛ ЖИЗНИ?</b>\n\nВы когда-нибудь задумывались над этим вопросом? Если поиск ответа для вас до сих пор актуален, рекомендую дочитать до конца!👇🏻\n\nПредлагаю взглянуть на этот вопрос под другим углом. <b>Что, если нам не нужно отвечать на него?</b> Что если <b>НЕ МЫ</b> задаем жизни вопрос «<b>в чём твой смысл?</b>», а <b>ЖИЗНЬ НАМ?</b>\n\nЕжедневно, сталкивая нас с различными трудностями, жизнь спрашивает у нас «<i>А в чём твой смысл?</i>». А наша задача - <b>своими поступками</b> ответить на этот вопрос. В таком случае нам не нужно искать смысл в жизни. Нам важно <b>увидеть его в себе</b>❤️\n\n<b>ВАШ СМЫСЛ</b> - это пересечение ваших ценностей в данный момент времени. Получается, важно просто понять свои ценности и начать их реализовывать в каждом дне?\n\nЕсли вам откликается такой подход, приглашаю вас <b>вместе поисследовать свой смысл</b> на моём авторском курсе «Как найти своё предназначение?»⬇️"

text_5 = "<b>ВАМ ТОЧНО ЭТО НАДО, ЕСЛИ…</b>\n\n💛Вы учитесь <b>в школе</b>, подходит время принимать решение, <b>куда же поступить</b>, но вы в растерянности и совсем не знаете, что выбрать. Возможно, вам интересно много сфер, а возможно, наоборот, будто не интересует ничего…А может, вы боитесь, что интересующая вас сфера не принесет желаемый доход и поэтому сомневаетесь в выборе?\n\n💛Вы <b>уже поступили</b>, но столкнулись с ощущением «<i>кажется, это не моё…</i>». И вот возникает вопрос «<i>Что делать дальше?</i>».\n\nПредставляете, есть даже термин - <b>кризис 2 курса</b>: с момента выбора будущей профессии вы выросли, ваши взгляды на жизнь поменялись и теперь вы в сомнениях: куда ли я пошла? Отчислиться или доучиться? <i>Что делать после окончания учебы?</i>\n\n💛Вы <b>уже закончили</b> учебное заведение, но что делать дальше – загадка. Вы точно знаете, что ваша профессия вам не нравится, но что нравится – не понимаете. С одной стороны – хочется зарабатывать деньги, с другой – не хочется всю жизнь горбатиться на нелюбимой работе.\n\nМне до безумия знакомы все эти чувства, и я хочу помочь вам справиться с этим. Поэтому приглашаю на курс «Как найти своё предназначение?»\n<i>(90% практики и только 10% теории)</i>\n\n<b>КАКОЙ РЕЗУЛЬТАТ ВЫ ПОЛУЧИТЕ</b>👇🏻\n\nВы научитесь <b>понимать себя</b>, свои желания, эмоции, потребности, ценности. Научитесь выстраивать более гармоничные <b>отношения</b> с окружающими, близкими. Это всё, в конечном итоге, поможет вам <b>найти себя</b>. Вы получите большое количество инструментов, которые помогут вам понять своё предназначение и <b>чётко сформулировать свою миссию в жизни</b>. Вы научитесь <b>планировать свою жизнь</b> так, чтобы каждый день приближал вас к исполнению мечты и реализации предназначения. Дни наконец перестанут быть бессмысленными, серыми и однообразными. Вы наконец сможете <b>избавиться от постоянных метаний</b>, непонятного, всепоглощающего чувства «<i>я не знаю, чего я хочу от жизни</i>». Вы найдёте для себя свой смысл жизни. И поймёте, как его воплотить.\n\n<i>Но всё зависит и от ваших стараний тоже ;)</i>"

text_6 = "<b>А ВДРУГ У МЕНЯ НЕ ПОЛУЧИТСЯ?</b>\n\nВам знакомо это опасение?\n<i>«Вдруг я куплю курс, потрачу время, силы, деньги, а результата не будет…?»</i>🥺\n\nЗнаете, <b>результат - это относительное понятие.</b> Как вы поймёте, получили ли вы результат? Если вы просто теоретически поймёте своё предназначение? Или если ваша жизнь перевернётся на 180 градусов и вы станете другим человеком? Если смените работу и пойдёте пробовать новое? Или если просто начнёте чуть лучше понимать себя, слышать свои желания?\n\n<b>Поиск своего предназначения - это процесс.</b> И сделав шаг в его сторону, вы в любом случае запустите этот процесс. Я дам вам все инструменты, а дальше всё будет зависеть от вас🤲🏻\n\nА не попробовав, вы даже не узнаете, ответ на вопрос в начале этого сообщения :)"

text_7 = "<b>Когда человек занимается тем, что ему нравится, успех приходит сам.</b> Когда мы играем чужие роли, мы всегда будем неуспешны.\n\nПоверьте, я знаю, о чём говорю, ведь в своей жизни я была и почтальоном, и няней, и официанткой, и SMM, и безработной. Я поступала, казалось, в ВУЗ мечты, а потом розовые очки с треском разбивались. И в этом треске было слышно тихое «<i>Похоже, это не моё…</i>». А потом тишина и непонимание, куда идти дальше😔\n\nМне казалось, что если стараться, работать без выходных, идти к своим целям, то успех придет. Но только я забыла узнать, какие цели были действительно мои. И только когда я перестала бежать, остановилась и спросила себя «<i>а чего я действительно хочу?</i>», «<i>а ведут ли мои действия меня к моим мечтам?</i>», тогда я всё поняла…\n\nОказалось, можно было работать в своё <b>удовольствие</b> и позволять себе отдыхать. Достаточно просто <b>делать то, что действительно любишь</b>, и успех начнёт приходить без переработок. Раз - и первый миллион просмотров. Одно видео - а у меня уже 200+ заявок на консультации. Я думала, так не бывает💔\n\n<b>Вспомните сейчас свою жизнь.</b> Были ли у вас ситуации, когда казалось, что как бы ты ни старался, ничего не получается? А ситуации, где всё будто складывалось само собой? Думаете, это просто совпадения?"

text_8 = "<b>КАК СПРАВИТЬСЯ СО СТРАХОМ?</b>\n\nВсе эмоции, которые мы испытываем, являются <b>полезными сигналами</b>. Природа создала их не для того, чтобы испортить нам жизнь. У каждой эмоции есть своя <b>функция</b>✨\n\nСтрах даёт нам <b>энергию для ухода от опасности.</b> Он заложен в нашей психике, чтобы увидев медведя в кустах, мы спрятались или убежали, тем самым спасли свою жизнь.\n\nНо сейчас в нашем мире такое количество стимулов, что мы можем начать бояться всего, без разбора, что представляет реальную опасность, а что нет. Так появляется тревожность - постоянный страх о чисто теоретическом будущем. Такая эмоция может привести к отказу от многих возможностей😔\n\n<i>Боюсь, что ничего не получится // что потеряю время → вообще не буду пробовать</i>\n\nСтрах – еще и самая опасная эмоция, которая оказывает <b>влияние на наше сознание и поведение.</b> Он может буквально блокировать нас и наше развитие. Вот что действительно страшно😡\n\nТак что же делать?\nПризнайте свой страх, заметьте его, дайте ему место. Вам можно бояться.\nТеперь страх не управляет вами. Как только вы осознаете его, у вас появляется прекрасная возможность – выбирать: «<i>Да, я боюсь, но не смотря на это я могу идти за своими желаниями</i>»\n\n<i>Я живу всю осознанную жизнь с девизом «Бойся, но делай».</i> И он помог мне добиться того, что я имею.\n\nЕсли чувствуешь, что готов(а) попробовать искать себя, несмотря на страх, жми на кнопочку ниже 👇🏻"

text_9 = "<b>КАЖЕТСЯ, ЭТО НЕ МОЁ…</b>👀\n\nИ в этот момент весь фундамент, который ты так долго выстраивал, будто рушится под ногами. Как то, над чем я так старательно работала, может оказаться не моим?\n\nТы просто однажды просыпаешься с мыслью «<i>Я не хочу дальше жить ТАК.</i>». И что теперь делать с этой мыслью? Может забыть, отмахнуться, сделать вид, что не заметил её, и просто жить как раньше? Но как раньше уже не получится, ведь с каждым днём эта мысль будет всё громче кричать тебе «<i>пора что-то менять!</i>»😭\n\nИменно это я пережила, когда осознала, что место, в котором я проучилась 2 года (а до этого ещё потратила огромное количество усилий, чтобы поступить на бюджет) – не моё.\n\nКартина маслом: я сижу на паре и мысль, которую я неделями подавляла, не выдерживает и начинает неистово кричать в голове:\n• «Я не хочу здесь быть»\n• «Я не на своём месте»\n• «Я не должна быть тут»\n\nНа глазах наворачиваются слёзы, я убегаю в туалет и остаюсь наедине с желанием прямо сейчас забрать документы и не возвращаться никогда.\nЭто была моя последняя пара в НГУ.\n\nНо настоящий ад начался потом. Когда пришлось сказать маме, а потом и всем остальным. На протяжении года я ежедневно выслушивала от огромного количества людей осуждение и попытки переубедить. Мне даже говорили, что я не смогу построить с Колей семью из-за того, что у нас будут разные взгляды (ведь он закончил НГУ, а я нет)\n\nНо я не послушала никого, кроме себя, ведь с каждым днём убеждалась, что делаю всё правильно (хотя откаты тоже были). И теперь безумно благодарна себе, ведь всё сложилось наилучшим образом! А стоило лишь понять себя🤍\n\nЕсли тебе знакомы такие переживания, ещё <b>можно присоединиться</b> к моему проекту «Как найти своё предназначение?», пока осталось <b>несколько свободных мест!</b> Там я на протяжении <b>24 дней</b> буду помогать вам найти себя с помощью различных практик и знаний, которые в своё время помогли мне⬇️"

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

def kb_pay_with_receipt(price: Tuple[int, int]) -> InlineKeyboardMarkup:
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
_user_locks = WeakValueDictionary()


def user_lock(user_id):
    lock = _user_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _user_locks[user_id] = lock
    return lock


class DeliveryUncertain(RuntimeError):
    """An interrupted Telegram request must not be replayed automatically."""

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def dt_to_ts(dt: datetime) -> int:
    return int(dt.timestamp())

async def db_init():
    global _conn, TEST_MODE

    logging.info(f"Using DB path: {os.path.abspath(DB_PATH)}")

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

    await _ensure_column("users", "discount_until", "INTEGER")
    await _ensure_column("users", "awaiting_receipt", "INTEGER DEFAULT 0")
    await _ensure_column("users", "paid", "INTEGER DEFAULT 0")

    await _ensure_column("queue", "interval_seconds", "INTEGER")
    await _ensure_column("queue", "retry_at", "REAL")
    await _ensure_column("queue", "cancelled_at", "REAL")
    await _ensure_column("queue", "media_sent_at", "REAL")
    await _ensure_column("queue", "delivery_phase", "TEXT")
    await _ensure_column("queue", "uncertain_at", "REAL")
    await _ensure_column("queue", "message_id", "INTEGER")
    # Recover intervals from the original schedule once, before any rescheduling.
    _conn.execute("""
        UPDATE queue SET interval_seconds=CASE
            WHEN step=2 THEN 2400
            ELSE COALESCE(
                (SELECT queue.run_at - previous.run_at FROM queue AS previous
                 WHERE previous.user_id=queue.user_id AND previous.step=queue.step-1),
                CASE WHEN step=3 THEN 86400 ELSE 172800 END
            ) END
        WHERE interval_seconds IS NULL AND step BETWEEN 2 AND 10
    """)
    _conn.execute("""
        CREATE INDEX IF NOT EXISTS queue_pending_due ON queue(run_at, user_id, step)
        WHERE sent_at IS NULL AND cancelled_at IS NULL
    """)
    init_stats(_conn)
    receipts.init_receipts(_conn)
    init_settings(_conn, TEST_MODE)
    _conn.execute("""
        UPDATE queue SET uncertain_at=COALESCE(uncertain_at, ?)
        WHERE delivery_phase IS NOT NULL AND sent_at IS NULL AND cancelled_at IS NULL
    """, (utcnow().timestamp(),))
    _conn.commit()
    TEST_MODE = get_test_mode(_conn)
    repair_pending_schedules()

    # Older versions precomputed a deadline at /start, before delivery.
    await db_exec(
        "UPDATE users SET discount_until=NULL WHERE user_id IN "
        "(SELECT user_id FROM queue WHERE step=2 AND sent_at IS NULL)"
    )

async def _ensure_column(table: str, col: str, coltype: str):
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


def repair_pending_schedules():
    """Repair only untouched partial schedules left by the old /start code."""
    with _conn:
        for user_id, started_at in _conn.execute("SELECT user_id, started_at FROM users WHERE paid=0").fetchall():
            if started_at is None:
                continue
            rows = _conn.execute("""
                SELECT step, run_at, interval_seconds, sent_at, cancelled_at, delivery_phase, media_sent_at
                FROM queue WHERE user_id=? AND step BETWEEN 2 AND 10 ORDER BY step
            """, (user_id,)).fetchall()
            if len(rows) == 9 or any(any(value is not None for value in row[3:]) for row in rows):
                continue
            existing = {row[0]: row for row in rows}
            fast = any(row[2] == TEST_DELAY_SECONDS for row in rows)
            if 2 in existing:
                fast = 0 < existing[2][1] - int(started_at) <= TEST_DELAY_SECONDS
            elif not rows:
                fast = is_test_user(user_id)
            cursor = int(started_at)
            for step in range(2, 11):
                interval = TEST_DELAY_SECONDS if fast else (2400 if step == 2 else 86400 if step == 3 else 172800)
                if step in existing:
                    cursor = existing[step][1]
                else:
                    cursor += interval
                    _conn.execute("INSERT INTO queue(user_id, step, run_at, interval_seconds) VALUES(?,?,?,?)",
                                  (user_id, step, cursor, interval))


# ================= ПЛАН ВОРОНКИ =================

def build_schedule(start_dt: datetime, user_id: Optional[int] = None) -> List[Tuple[int, int]]:
    t0 = start_dt

    t2 = t0 + timedelta(seconds=delay(minutes=40, user_id=user_id))

    schedule = []
    schedule.append((2, dt_to_ts(t2)))

    t3 = t2 + timedelta(seconds=delay(hours=24, user_id=user_id))
    schedule.append((3, dt_to_ts(t3)))

    t4 = t3 + timedelta(seconds=delay(hours=48, user_id=user_id))
    schedule.append((4, dt_to_ts(t4)))

    cur = t4
    for step in range(5, 11):
        cur = cur + timedelta(seconds=delay(hours=48, user_id=user_id))
        schedule.append((step, dt_to_ts(cur)))

    return schedule

async def enqueue_user(user_id: int, username: Optional[str]):
    now = utcnow()
    now_ts = now.timestamp()

    schedule = build_schedule(now, user_id=user_id)
    rows = []
    previous_run_at = dt_to_ts(now)
    for step, run_at in schedule:
        rows.append((user_id, step, run_at, run_at - previous_run_at))
        previous_run_at = run_at
    async with _db_lock:
        with _conn:
            _conn.execute("""
                INSERT INTO users(user_id, username, started_at, paid, discount_until, awaiting_receipt)
                VALUES(?,?,?,0,NULL,0) ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username, started_at=excluded.started_at, paid=0,
                discount_until=NULL, awaiting_receipt=0, receipt_received_at=NULL, receipt_quote_id=NULL
            """, (user_id, username, now_ts))
            _conn.execute("DELETE FROM queue WHERE user_id=?", (user_id,))
            _conn.executemany(
                "INSERT INTO queue(user_id, step, run_at, interval_seconds) VALUES(?,?,?,?)", rows
            )

async def reset_user_db(user_id: int):
    async with _db_lock:
        with _conn:
            _conn.execute("DELETE FROM queue WHERE user_id=?", (user_id,))
            _conn.execute("DELETE FROM users WHERE user_id=?", (user_id,))

async def is_paid(user_id: int) -> bool:
    row = await db_fetchone("SELECT paid FROM users WHERE user_id=?", (user_id,))
    return bool(row and row[0] == 1)

async def already_started(user_id: int) -> bool:
    row = await db_fetchone("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    return row is not None

async def get_current_price(user_id: int) -> Tuple[int, int]:
    row = await db_fetchone("SELECT discount_until FROM users WHERE user_id=?", (user_id,))
    if not row or not row[0]:
        return FULL_PRICE
    discount_until = float(row[0])
    return DISCOUNT_PRICE if utcnow().timestamp() < discount_until else FULL_PRICE

async def set_awaiting_receipt(user_id: int, value: int):
    await db_exec("UPDATE users SET awaiting_receipt=? WHERE user_id=?", (value, user_id))

async def is_awaiting_receipt(user_id: int) -> bool:
    row = await db_fetchone("SELECT awaiting_receipt FROM users WHERE user_id=?", (user_id,))
    return bool(row and int(row[0]) == 1)

async def confirm_purchase(user_id: int):
    now_ts = utcnow().timestamp()
    async with _db_lock:
        with _conn:
            _conn.execute("UPDATE users SET paid=1, awaiting_receipt=0, receipt_received_at=COALESCE(receipt_received_at, ?) WHERE user_id=?", (now_ts, user_id))
            _conn.execute("UPDATE queue SET cancelled_at=? WHERE user_id=? AND sent_at IS NULL AND cancelled_at IS NULL", (now_ts, user_id))


# ================= ОТПРАВКА ПО ШАГУ =================

async def mark_uncertain(qid):
    await db_exec("UPDATE queue SET uncertain_at=? WHERE id=? AND delivery_phase IS NOT NULL AND sent_at IS NULL AND cancelled_at IS NULL", (utcnow().timestamp(), qid))


async def telegram_delivery(qid, phase, operation):
    async with _db_lock:
        with _conn:
            claimed = _conn.execute("""
                UPDATE queue SET delivery_phase=? WHERE id=? AND sent_at IS NULL
                AND cancelled_at IS NULL AND delivery_phase IS NULL AND uncertain_at IS NULL
                AND EXISTS (SELECT 1 FROM users WHERE user_id=queue.user_id AND paid=0)
            """, (phase, qid))
            if not claimed.rowcount:
                return False, None
    try:
        result = await operation()
    except (TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter):
        await db_exec("UPDATE queue SET delivery_phase=NULL WHERE id=?", (qid,))
        raise
    except TelegramNetworkError as error:
        # A failed TCP/DNS connection never reached Telegram. Other network errors
        # may have occurred after acceptance and cannot safely be retried.
        if isinstance(error.__cause__, ClientConnectorError):
            await db_exec("UPDATE queue SET delivery_phase=NULL WHERE id=?", (qid,))
            raise
        await mark_uncertain(qid)
        raise DeliveryUncertain() from error
    except asyncio.CancelledError:
        await mark_uncertain(qid)
        raise
    except Exception as error:
        await mark_uncertain(qid)
        raise DeliveryUncertain() from error
    return True, result


async def send_step(user_id: int, step: int, queue_id: Optional[int] = None):
    if await is_paid(user_id):
        logging.info("Skip paid user=%s step=%s", user_id, step)
        return False
    row = await db_fetchone("""
        SELECT id, media_sent_at FROM queue WHERE user_id=? AND step=?
        AND sent_at IS NULL AND cancelled_at IS NULL AND (? IS NULL OR id=?)
    """, (user_id, step, queue_id, queue_id))
    if not row:
        return False
    qid, media_sent_at = row
    logging.info("send_step user=%s step=%s", user_id, step)
    if step == 2 and media_sent_at is None:
        media = [InputMediaPhoto(media=fid) for fid in STEP2_PHOTOS]
        delivered, _ = await telegram_delivery(qid, "media", lambda: bot.send_media_group(chat_id=user_id, media=media))
        if not delivered:
            return False
        async with _db_lock:
            with _conn:
                updated = _conn.execute("""
                    UPDATE queue SET media_sent_at=?, delivery_phase=NULL WHERE id=?
                    AND sent_at IS NULL AND cancelled_at IS NULL
                """, (utcnow().timestamp(), qid))
                if not updated.rowcount:
                    return False
    messages = {
        2: (text_2, kb_action("купить", "pay")),
        3: (text_3, kb_action("ХОЧУ", "pay")),
        4: (text_4, kb_details_and_go("УЗНАТЬ ПОДРОБНОСТИ", "ПРИНЯТЬ УЧАСТИЕ")),
        5: (text_5, kb_details_and_go("УЗНАТЬ ПОДРОБНОСТИ", "ЗАПИСАТЬСЯ")),
        6: (text_6, kb_details_and_go("ПОДРОБНЕЕ", "Я ИДУ!")),
        7: (text_7, kb_action("ПОНЯТЬ, ЧЕМ ХОЧУ ЗАНИМАТЬСЯ", "pay")),
        8: (text_8, kb_details_and_go("РАССКАЖИ ПОДРОБНЕЕ", "УГОВОРИЛА")),
        9: (text_9, kb_action("ДЕЛАЕМ!", "pay")),
        10: (text_10, kb_action("ЛЕТС ГОУ", "pay")),
    }
    if step not in messages:
        return False
    text, keyboard = messages[step]
    delivered, result = await telegram_delivery(qid, "text", lambda: bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard))
    if not delivered:
        return False
    message_id = getattr(result, "message_id", None)
    await record_step_delivery(user_id, step, utcnow().timestamp(), queue_id=qid,
                               message_id=message_id if isinstance(message_id, int) else None)
    return True


def _reschedule_remaining(user_id: int, step: int, completed_at: float):
    next_at = completed_at
    rows = _conn.execute(
        "SELECT id, interval_seconds FROM queue WHERE user_id=? AND step>? AND step<=10 "
        "AND sent_at IS NULL AND cancelled_at IS NULL ORDER BY step", (user_id, step)
    ).fetchall()
    for qid, interval in rows:
        next_at += interval
        _conn.execute("UPDATE queue SET run_at=?, retry_at=NULL WHERE id=?", (next_at, qid))


async def record_step_delivery(user_id: int, step: int, sent_at: float, queue_id: Optional[int] = None, message_id=None):
    async with _db_lock:
        with _conn:
            updated = _conn.execute(
                "UPDATE queue SET sent_at=?, retry_at=NULL, delivery_phase=NULL, uncertain_at=NULL, message_id=? WHERE user_id=? AND step=? "
                "AND sent_at IS NULL AND cancelled_at IS NULL AND (? IS NULL OR id=?)", (sent_at, message_id, user_id, step, queue_id, queue_id)
            )
            if not updated.rowcount:
                return
            if step == 2:
                _conn.execute("UPDATE users SET discount_until=? WHERE user_id=?",
                              (sent_at + discount_duration(user_id), user_id))
            _reschedule_remaining(user_id, step, sent_at)


async def get_due_queue_items():
    now = utcnow().timestamp()
    return await db_fetchall(
        "SELECT q.id, q.user_id, q.step FROM queue AS q JOIN users AS u ON u.user_id=q.user_id "
        "WHERE q.sent_at IS NULL AND q.cancelled_at IS NULL AND u.paid=0 "
        "AND q.delivery_phase IS NULL AND q.uncertain_at IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM receipt_deliveries AS r WHERE r.user_id=u.user_id "
        "AND r.generation=(SELECT MIN(id) FROM queue WHERE user_id=u.user_id AND step BETWEEN 2 AND 10)) "
        "AND q.step BETWEEN 2 AND 10 AND q.run_at<=? AND COALESCE(q.retry_at, 0)<=? "
        "AND NOT EXISTS (SELECT 1 FROM queue AS earlier WHERE earlier.user_id=q.user_id "
        "AND earlier.step BETWEEN 2 AND 10 AND earlier.step<q.step "
        "AND earlier.sent_at IS NULL AND earlier.cancelled_at IS NULL) "
        "ORDER BY q.run_at, q.id LIMIT 50", (now, now)
    )


async def cancel_queue_item(user_id: int, step: int, blocked: bool, queue_id: int):
    now = utcnow().timestamp()
    async with _db_lock:
        with _conn:
            pending = _conn.execute(
                "SELECT 1 FROM queue WHERE id=? AND user_id=? AND step=? AND sent_at IS NULL AND cancelled_at IS NULL",
                (queue_id, user_id, step),
            ).fetchone()
            if not pending:
                return
            if blocked:
                _conn.execute("UPDATE queue SET cancelled_at=? WHERE user_id=? AND sent_at IS NULL AND cancelled_at IS NULL",
                              (now, user_id))
            else:
                _conn.execute("UPDATE queue SET cancelled_at=? WHERE user_id=? AND step=? AND sent_at IS NULL",
                              (now, user_id, step))
                _reschedule_remaining(user_id, step, now)


async def process_queue_item(qid: int, user_id: int, step: int):
    try:
        await asyncio.wait_for(send_step(user_id, step, queue_id=qid), timeout=QUEUE_SEND_TIMEOUT)
    except TelegramForbiddenError:
        logging.warning("Queue cancelled for blocked/inaccessible user=%s", user_id)
        await cancel_queue_item(user_id, step, blocked=True, queue_id=qid)
    except TelegramBadRequest:
        logging.error("Invalid Telegram message user=%s step=%s; cancelling this step", user_id, step)
        await cancel_queue_item(user_id, step, blocked=False, queue_id=qid)
    except TelegramRetryAfter as error:
        await db_exec("UPDATE queue SET retry_at=? WHERE id=? AND sent_at IS NULL AND cancelled_at IS NULL",
                      (utcnow().timestamp() + max(1, error.retry_after), qid))
        logging.warning("Telegram rate limit user=%s step=%s; retry in %ss", user_id, step, error.retry_after)
    except DeliveryUncertain:
        logging.warning("Uncertain delivery queue_id=%s user=%s step=%s; awaiting review", qid, user_id, step)
    except Exception as error:
        row = await db_fetchone("SELECT delivery_phase FROM queue WHERE id=?", (qid,))
        if row and row[0]:
            await mark_uncertain(qid)
            logging.warning("Delivery checkpoint failed queue_id=%s; awaiting review", qid)
            return
        logging.warning("Temporary queue error user=%s step=%s type=%s; retry deferred", user_id, step, type(error).__name__)
        await db_exec("UPDATE queue SET retry_at=? WHERE id=? AND sent_at IS NULL AND cancelled_at IS NULL",
                      (utcnow().timestamp() + QUEUE_RETRY_SECONDS, qid))


async def process_receipt_delivery(delivery_id):
    now = utcnow().timestamp()
    async with _db_lock:
        payload = receipts.claim_delivery(_conn, delivery_id, now, now - QUEUE_SEND_TIMEOUT - QUEUE_RETRY_SECONDS)
    if payload is None:
        return
    admin_id, kind, file_id, caption = payload
    try:
        if kind == "photo":
            await asyncio.wait_for(bot.send_photo(admin_id, photo=file_id, caption=caption), timeout=QUEUE_SEND_TIMEOUT)
        else:
            await asyncio.wait_for(bot.send_document(admin_id, document=file_id, caption=caption), timeout=QUEUE_SEND_TIMEOUT)
    except asyncio.CancelledError:
        async with _db_lock:
            receipts.defer_delivery(_conn, delivery_id, utcnow().timestamp() + QUEUE_RETRY_SECONDS, "Interrupted")
        raise
    except Exception as error:
        pause = max(1, error.retry_after) if isinstance(error, TelegramRetryAfter) else (
            3600 if isinstance(error, (TelegramForbiddenError, TelegramBadRequest)) else QUEUE_RETRY_SECONDS
        )
        async with _db_lock:
            receipts.defer_delivery(_conn, delivery_id, utcnow().timestamp() + pause, type(error).__name__)
        logging.warning("Receipt forward deferred id=%s admin=%s type=%s", delivery_id, admin_id, type(error).__name__)
    else:
        try:
            async with _db_lock:
                receipts.finish_delivery(_conn, delivery_id, utcnow().timestamp())
        except sqlite3.Error as error:
            logging.warning("Receipt checkpoint failed id=%s type=%s; durable payload retained", delivery_id, type(error).__name__)
            try:
                async with _db_lock:
                    receipts.defer_delivery(_conn, delivery_id, utcnow().timestamp() + QUEUE_RETRY_SECONDS, "CheckpointFailed")
            except sqlite3.Error:
                # The persisted claim also expires, so a DB outage cannot leave it stuck.
                logging.warning("Receipt claim retained id=%s; will retry after expiry", delivery_id)


async def get_due_receipts():
    return await db_fetchall("""
        SELECT id FROM receipt_deliveries WHERE sent_at IS NULL AND (sending_at IS NULL OR sending_at<=?)
        AND COALESCE(retry_at, 0)<=? ORDER BY COALESCE(retry_at, 0), id LIMIT 50
    """, (utcnow().timestamp() - QUEUE_SEND_TIMEOUT - QUEUE_RETRY_SECONDS, utcnow().timestamp()))


# ================= ВОРКЕР ОЧЕРЕДИ =================

async def queue_worker():
    logging.info("Queue worker started")
    active = {}
    try:
        while True:
            try:
                for key, task in list(active.items()):
                    if task.done():
                        del active[key]
                        try:
                            task.result()
                        except Exception:
                            logging.exception("Queue task failed key=%s", key)
                if len(active) < QUEUE_CONCURRENCY:
                    for (delivery_id,) in await get_due_receipts():
                        key = ("receipt", delivery_id)
                        if key not in active:
                            active[key] = asyncio.create_task(process_receipt_delivery(delivery_id))
                        if len(active) >= QUEUE_CONCURRENCY:
                            break
                if len(active) < QUEUE_CONCURRENCY:
                    for qid, user_id, step in await get_due_queue_items():
                        key = ("funnel", user_id)
                        if key in active:
                            continue
                        active[key] = asyncio.create_task(process_queue_item(qid, user_id, step))
                        if len(active) >= QUEUE_CONCURRENCY:
                            break
                if active:
                    await asyncio.wait(active.values(), timeout=0.2, return_when=asyncio.FIRST_COMPLETED)
                else:
                    await asyncio.sleep(1 if TEST_MODE else 3)
            except Exception:
                logging.exception("Worker loop error")
                await asyncio.sleep(3)
    finally:
        for task in active.values():
            task.cancel()
        await asyncio.gather(*active.values(), return_exceptions=True)


# ================= PAY FLOW =================

def format_price(price: int) -> str:
    return f"{price:,}".replace(",", " ")


def payment_message(price: Tuple[int, int]) -> str:
    without_feedback, with_feedback = price
    return (
        "Благодарю за доверие! Давай руку и пойдём вместе искать твоё предназначение 🫴🏻🫴🏻\n\n"
        "Для оплаты места на курсе выбери подходящий для тебя тариф:\n"
        f"1️⃣ {format_price(without_feedback)} ₽ — без обратной связи от меня\n"
        f"2️⃣ {format_price(with_feedback)} ₽ — с обратной связью от меня\n\n"
        "Просто переведи соответствующую сумму ПО РЕКВИЗИТАМ 👇🏻\n\n"
        "<b>Номер телефона:</b> 89938132956\n"
        "<b>ИЛИ номер карты:</b> 2200010179100253\n"
        "Газпромбанк\n"
        "Получатель: Лобанова Маргарита Сергеевна\n\n"
        "После оплаты пришли чек сюда, я проверю его и добавлю тебя в чат курса✨"
    )


# ================= HANDLERS =================

@dp.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    async with user_lock(user_id):
        username = message.from_user.username
        if await already_started(user_id):
            await message.answer("Ты уже проходишь воронку 💛\nЕсли хочешь заново — напиши /reset")
            return
        if VIDEO_ENABLED:
            await message.answer_video(video=VIDEO_FILE_ID, caption=text_1)
        else:
            await message.answer(text_1)
        try:
            await enqueue_user(user_id, username)
        except sqlite3.Error as error:
            logging.error("Start transaction failed user=%s type=%s", user_id, type(error).__name__)
            await message.answer("Не удалось сохранить начало прохождения. Попробуй отправить /start ещё раз чуть позже.")
            return
        logging.info("User enqueued %s @%s", user_id, username)


@dp.message(F.text == "/reset")
async def reset_cmd(message: Message):
    async with user_lock(message.from_user.id):
        await reset_user_db(message.from_user.id)
        await message.answer("Ок 👌 Я забыл(а) тебя. Можешь снова нажать /start")

@dp.message(F.video)
async def get_video_id(message: Message):
    await message.answer(f"VIDEO_FILE_ID:\n<code>{message.video.file_id}</code>")

@dp.callback_query(F.data == "details")
async def details_cb(callback: CallbackQuery):
    user_id = callback.from_user.id

    media = [InputMediaPhoto(media=fid) for fid in STEP2_PHOTOS]
    await bot.send_media_group(chat_id=user_id, media=media)

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

    await reconcile_offer_callback(callback)
    price = await get_current_price(user_id)
    result = await callback.message.answer(payment_message(price), reply_markup=kb_pay_with_receipt(price))
    try:
        async with _db_lock:
            receipts.save_quote(_conn, user_id, getattr(getattr(result, "chat", None), "id", user_id),
                                result.message_id, price, utcnow().timestamp())
    except sqlite3.Error as error:
        # The trusted callback's original payment text can recover this exact quote.
        logging.warning("Payment quote checkpoint failed user=%s type=%s", user_id, type(error).__name__)
    await callback.answer()

@dp.callback_query(F.data == "send_receipt")
async def send_receipt_cb(callback: CallbackQuery):
    user_id = callback.from_user.id

    if await is_paid(user_id):
        await callback.message.answer("Ты уже отправил(а) чек ✅ Оплату проверит администратор.")
        await callback.answer()
        return

    if not await already_started(user_id):
        await callback.message.answer("Сначала отправь /start, затем снова нажми кнопку отправки чека.")
        await callback.answer()
        return
    try:
        async with _db_lock:
            # Old payment messages can also supply their original displayed price.
            text = getattr(callback.message, "text", None)
            chat_id = callback.message.chat.id
            for prices in (DISCOUNT_PRICE, FULL_PRICE):
                if (text == unescape(re.sub(r"</?[bi]>", "", payment_message(prices)))
                        and callback.message.from_user.id == bot.id and chat_id == user_id
                        and getattr(callback.message, "forward_origin", None) is None):
                    receipts.save_quote(_conn, user_id, chat_id, callback.message.message_id, prices, utcnow().timestamp())
            receipts.select_quote(_conn, user_id, chat_id, callback.message.message_id)
    except sqlite3.Error as error:
        logging.warning("Receipt preparation failed user=%s type=%s", user_id, type(error).__name__)
        await callback.message.answer("Не удалось подготовить отправку чека. Попробуй нажать кнопку ещё раз чуть позже.")
        await callback.answer()
        return
    await callback.message.answer("Отправь, пожалуйста, фото или файл чека сюда 👇")
    await callback.answer()


async def reconcile_offer_callback(callback):
    message = callback.message
    if (getattr(message, "text", None) != unescape(re.sub(r"</?[bi]>", "", text_2))
            or getattr(getattr(message, "from_user", None), "id", None) != bot.id
            or getattr(getattr(message, "chat", None), "id", None) != callback.from_user.id):
        return
    row = await db_fetchone("""
        SELECT q.id FROM queue AS q JOIN users AS u ON u.user_id=q.user_id
        WHERE q.user_id=? AND q.step=2 AND q.delivery_phase='text'
        AND q.sent_at IS NULL AND q.cancelled_at IS NULL AND u.started_at<=?
    """, (callback.from_user.id, message.date.timestamp()))
    if row:
        # Telegram's callback contains evidence of this exact message and its date.
        await record_step_delivery(callback.from_user.id, 2, message.date.timestamp(),
                                   queue_id=row[0], message_id=message.message_id)

def receipt_caption(message, price, received_at):
    name = escape(message.from_user.full_name[:120])
    username = escape(message.from_user.username[:64]) if message.from_user.username else "—"
    tariff = (
        f"Тарифы при нажатии покупки: <b>{format_price(price[0])} ₽ / {format_price(price[1])} ₽</b>"
        if price else "Тариф ранее не зафиксирован; сумму проверьте по чеку."
    )
    return (
        f"✅ <b>ЧЕК ПОЛУЧЕН</b>\nUser: <b>{name}</b>\n"
        f"Username: @{username}\nUser ID: <code>{message.from_user.id}</code>\n"
        f"{tariff}\nВремя (UTC): {received_at.strftime('%Y-%m-%d %H:%M:%S')}"
    )


async def receive_receipt(message, kind, file_id):
    user_id = message.from_user.id
    async with user_lock(user_id):
        if not await is_awaiting_receipt(user_id):
            return
        received_at = utcnow()
        try:
            async with _db_lock:
                price = receipts.receipt_prices(_conn, user_id)
                caption = receipt_caption(message, price, received_at)
                delivery_ids = receipts.save_receipt(
                    _conn, user_id, message.chat.id, message.message_id, kind, file_id,
                    caption, received_at.timestamp(), ADMIN_IDS
                )
        except sqlite3.Error as error:
            logging.error("Receipt storage failed user=%s type=%s", user_id, type(error).__name__)
            await message.answer("Не удалось сохранить чек. Пожалуйста, пришли его ещё раз чуть позже — оплата пока не подтверждена.")
            return
        if not delivery_ids:
            return
        # All payloads are durable before any Telegram request is made.
        await asyncio.gather(*(process_receipt_delivery(delivery_id) for delivery_id in delivery_ids))
        if await is_paid(user_id):
            await message.answer("Спасибо! ✅ Чек получен. Я скоро подтвержу оплату 💛")
        else:
            await message.answer("Чек сохранён ✅ Сейчас не удалось передать его администратору. Я повторю отправку автоматически; присылать чек заново не нужно.")


@dp.message(F.photo)
async def receipt_photo(message: Message):
    await receive_receipt(message, "photo", message.photo[-1].file_id)


@dp.message(F.document)
async def receipt_document(message: Message):
    await receive_receipt(message, "document", message.document.file_id)


@dp.message(F.text == "/help")
async def help_cmd(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer(
        "<b>Доступные команды</b>\n\n"
        "/help - этот список команд\n"
        "/start - получить видео и начать прохождение\n"
        "/reset - сбросить только своё прохождение\n"
        "/status - режим, остаток скидки и статистика\n"
        "/stats - статистика за текущий период\n"
        "/reset_stats - начать новый период статистики без удаления пользователей и таймеров\n"
        "/test_on - тестовый режим: сообщения по 10 секунд, скидка 60 секунд для администраторов\n"
        "/test_off - обычный режим: первое сообщение через 40 минут, далее 24/48 часов, скидка 60 минут\n"
        "/debug_queue - посмотреть просроченные задания очереди\n\n"
        "/resolve_delivery ID retry - повторить спорную отправку после проверки\n"
        "/resolve_delivery ID media_sent - подтвердить, что фотографии дошли\n"
        "/resolve_delivery ID sent ВРЕМЯ - подтвердить доставку текста (время ISO UTC)\n\n"
        "После смены режима сохранённые таймеры остаются прежними. "
        "Чтобы пройти заново с новыми таймерами: /reset, затем /start."
    )


@dp.message(F.text.in_({"/test_on", "/test_off"}))
async def test_mode_cmd(message: Message):
    global TEST_MODE
    if message.from_user.id not in ADMIN_IDS:
        return
    enabled = message.text == "/test_on"
    async with _db_lock:
        set_test_mode(_conn, enabled)
        TEST_MODE = enabled
    mode = "Тестовый режим включён: сообщения каждые 10 секунд, скидка 60 секунд для администраторов." if enabled else "Обычный режим включён: скидка 60 минут, сообщения по обычному расписанию."
    await message.answer(
        mode + "\nВыбор сохранён и останется после перезапуска.\n"
        "Для нового прохождения с выбранными таймерами: /reset, затем /start.\n"
        "Проверка: /status."
    )


@dp.message(F.text == "/status")
async def status_cmd(message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        return
    row = await db_fetchone("SELECT discount_until FROM users WHERE user_id=?", (user_id,))
    remaining = max(0, float(row[0]) - utcnow().timestamp()) if row and row[0] else 0
    mode = "тестовый" if is_test_user(user_id) else "обычный"
    interval = "10 секунд" if is_test_user(user_id) else "40 минут после видео, далее 24/48 часов"
    discount = f"осталось {remaining:.1f} сек." if remaining > 0 else "не действует"
    async with _db_lock:
        statistics = format_stats(get_stats(_conn))
    await message.answer(
        f"Бот работает ✅\nРежим: <b>{mode}</b>\n"
        f"Новые сообщения: {interval}\n"
        f"Скидка для новых предложений: {discount_duration(user_id)} сек.\n"
        f"Твоя текущая скидка: {discount}\n\n"
        "Сохранённые таймеры не пересчитываются при переключении.\n"
        "Для нового прохождения: /reset, затем /start.\n\n" + statistics + "\n\n" + await delivery_status()
    )


@dp.message(F.text == "/stats")
async def stats_cmd(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    async with _db_lock:
        statistics = format_stats(get_stats(_conn))
    await message.answer(statistics)


@dp.message(F.text == "/reset_stats")
async def reset_stats_cmd(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    async with _db_lock:
        reset_stats(_conn, utcnow().timestamp())
    await message.answer("Начат новый период статистики ✅\nПользователи, чеки и таймеры сохранены. Посмотреть: /stats или /status.")


@dp.message(F.text == "/debug_queue")
async def debug_queue_cmd(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    rows = await db_fetchall(
        "SELECT user_id, step, run_at FROM queue "
        "WHERE sent_at IS NULL AND cancelled_at IS NULL AND run_at <= ? "
        "ORDER BY run_at ASC LIMIT 20",
        (dt_to_ts(utcnow()),)
    )

    if not rows:
        await message.answer("Просроченных сообщений нет ✅")
    else:
        lines = ["<b>Просроченные сообщения:</b>"]
        for user_id, step, run_at in rows:
            run_dt = datetime.fromtimestamp(run_at, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            lines.append(f"user={user_id}, step={step}, run_at={run_dt}")
        await message.answer("\n".join(lines))

    uncertain = await db_fetchall("""
        SELECT id, user_id, step, delivery_phase FROM queue
        WHERE uncertain_at IS NOT NULL AND sent_at IS NULL AND cancelled_at IS NULL ORDER BY id LIMIT 20
    """)
    if uncertain:
        await message.answer("<b>Отправки с неизвестным результатом:</b>\n" + "\n".join(
            f"ID={qid}, user={user_id}, step={step}, phase={phase}" for qid, user_id, step, phase in uncertain
        ) + "\nПроверьте доставку у пользователя перед /resolve_delivery.")


async def delivery_status():
    pending = (await db_fetchone("SELECT COUNT(*) FROM receipt_deliveries WHERE sent_at IS NULL"))[0]
    uncertain = (await db_fetchone("SELECT COUNT(*) FROM queue WHERE uncertain_at IS NOT NULL AND sent_at IS NULL AND cancelled_at IS NULL"))[0]
    return f"Пересылки чеков в ожидании: {pending}\nОтправки, требующие проверки: {uncertain}"


@dp.message(Command("resolve_delivery"))
async def resolve_delivery_cmd(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = message.text.split()
    if (len(parts) not in (3, 4) or not parts[1].isdigit() or len(parts[1]) > 19
            or not 0 < int(parts[1]) <= 2**63 - 1):
        await message.answer("Формат: /resolve_delivery ID retry | media_sent | sent 2026-09-16T12:00:00Z")
        return
    qid, action = int(parts[1]), parts[2]
    row = await db_fetchone("""
        SELECT user_id, step, delivery_phase FROM queue WHERE id=? AND uncertain_at IS NOT NULL
        AND sent_at IS NULL AND cancelled_at IS NULL
    """, (qid,))
    if row is None:
        await message.answer("Спорное задание не найдено. Посмотрите /debug_queue.")
        return
    if action == "sent" and len(parts) == 4:
        if row[2] != "text":
            await message.answer("Для фотографий используйте media_sent; sent подтверждает доставку текста.")
            return
        try:
            date = datetime.fromisoformat(parts[3].replace("Z", "+00:00"))
            if date.tzinfo is None or not 0 < date.timestamp() <= utcnow().timestamp():
                raise ValueError
        except ValueError:
            await message.answer("Укажите фактическое время доставки с часовым поясом, например 2026-09-16T12:00:00Z.")
            return
        await record_step_delivery(row[0], row[1], date.timestamp(), queue_id=qid)
    elif action in {"retry", "media_sent"} and len(parts) == 3:
        if action == "media_sent" and (row[1] != 2 or row[2] != "media"):
            await message.answer("media_sent применяется только к спорной отправке фотографий этапа 2.")
            return
        await db_exec("""
            UPDATE queue SET delivery_phase=NULL, uncertain_at=NULL, retry_at=NULL,
            media_sent_at=CASE WHEN ?='media_sent' THEN ? ELSE media_sent_at END
            WHERE id=? AND uncertain_at IS NOT NULL AND sent_at IS NULL AND cancelled_at IS NULL
        """, (action, utcnow().timestamp(), qid))
    else:
        await message.answer("Формат: /resolve_delivery ID retry | media_sent | sent 2026-09-16T12:00:00Z")
        return
    await message.answer("Решение сохранено ✅ Посмотрите /status. Повтор разрешайте только после проверки: при неизвестном результате он может создать дубль.")


# ================= ЗАПУСК =================

async def stop_background_tasks(worker):
    tasks = [worker, *list(_update_tasks)]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def main():
    logging.info("Бот запущен 🚀")
    await db_init()
    logging.info("TEST_MODE=%s; accelerated timers apply to admins only (%ss)", TEST_MODE, TEST_DELAY_SECONDS)
    worker = asyncio.create_task(queue_worker())
    try:
        await dp.start_polling(bot, close_bot_session=False)
    finally:
        await stop_background_tasks(worker)
        try:
            await bot.session.close()
        finally:
            _conn.close()

if __name__ == "__main__":
    asyncio.run(main())

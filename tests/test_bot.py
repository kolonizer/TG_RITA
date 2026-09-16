import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from xml.etree import ElementTree

# A syntactically valid dummy token; tests never contact Telegram.
with patch.dict(os.environ, {"BOT_TOKEN": "123456789:" + "x" * 35}):
    import bot as app


FIRST_MESSAGE = 'Ну как ты после просмотра?\n\nЕсли понимаешь, что тема тебе близка и хочется глубже в неё погрузиться, вместе поработать над пониманием себя: своих желаний, эмоций, потребностей, мечт и целей, приглашаю тебя присоединиться к полному курсу «Как найти своё предназначение?»❤️\u200d🩹\n\n📌Длительность курса - 24 дня, каждый из которых будет посвящен определенной теме (наполнение курса ты можешь подробно прочитать на фото). 90% курса - практика, и только минимум теории. Я специально подобрала различные техники, упражнения, медитации, практики и задания, с помощью которых ты сможешь не просто понять что-то на уровне мыслей и чувств, но и закрепить все инсайты действиями, ведь только наши поступки способны действительно изменить жизнь.\n\nКурс стартует 30 сентября, успевайте занять место! (Да, их количество ограничено, так как я самостоятельно буду со всеми общаться и отвечать каждому)\n\nСпециально для вас я даю скидку 30% ровно на час после отправки этого сообщения! В течение этого часа вы можете приобрести курс по одному из двух тарифов:\n1️⃣ С обратной связью от меня - 3 888 ₽ вместо 5 555 ₽\n2️⃣ Без обратной связи - 2 333 ₽ вместо 3 333 ₽🤯\n\n(Больше такой скидки не будет! А ограничение час - чтобы вы не тянули😋) '

PAYMENT_TEMPLATE = """Благодарю за доверие! Давай руку и пойдём вместе искать твоё предназначение 🫴🏻🫴🏻

Для оплаты места на курсе выбери подходящий для тебя тариф:
1️⃣ {without} ₽ — без обратной связи от меня
2️⃣ {with_feedback} ₽ — с обратной связью от меня

Просто переведи соответствующую сумму ПО РЕКВИЗИТАМ 👇🏻

Номер телефона: 89938132956
ИЛИ номер карты: 2200010179100253
Газпромбанк
Получатель: Лобанова Маргарита Сергеевна

После оплаты пришли чек сюда, я проверю его и добавлю тебя в чат курса✨"""


def telegram_text(text):
    root = ElementTree.fromstring("<root>" + text + "</root>")
    for element in root.iter():
        if element.tag not in {"root", "b", "i"}:
            raise AssertionError(f"Unexpected HTML tag: {element.tag}")
    plain = "".join(root.itertext())
    if len(plain.encode("utf-16-le")) // 2 > 4096:
        raise AssertionError("Message exceeds Telegram's text limit")
    return plain


class MessageTests(unittest.TestCase):
    def test_first_message_exact_text_and_html(self):
        self.assertEqual(telegram_text(app.text_2), FIRST_MESSAGE)
        self.assertEqual(app.bot.default.parse_mode, "HTML")
        for emphasis in [
            "<b>полному курсу</b>",
            "<b>24 дня</b>",
            "<b>90% курса - практика</b>",
            "<i>не просто понять</i>",
            "<i>закрепить все инсайты действиями</i>",
            "<b>скидку 30% ровно на час</b>",
        ]:
            self.assertIn(emphasis, app.text_2)

    def test_payment_messages_exact_text_and_html(self):
        for prices, without, with_feedback in [
            (app.DISCOUNT_PRICE, "2 333", "3 888"),
            (app.FULL_PRICE, "3 333", "5 555"),
        ]:
            with self.subTest(prices=prices):
                self.assertEqual(
                    telegram_text(app.payment_message(prices)),
                    PAYMENT_TEMPLATE.format(without=without, with_feedback=with_feedback),
                )


class DatabaseTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "bot.sqlite3")
        self.path_patch = patch.object(app, "DB_PATH", self.db_path)
        self.path_patch.start()
        app._db_lock = asyncio.Lock()
        await app.db_init()
        # Fractional seconds expose truncation errors at the hour boundary.
        self.sent = datetime(2026, 9, 16, 12, 0, 0, 750000, tzinfo=timezone.utc)
        self.fake_bot = SimpleNamespace(
            send_media_group=AsyncMock(), send_message=AsyncMock()
        )
        self.bot_patch = patch.object(app, "bot", self.fake_bot)
        self.bot_patch.start()
        with patch.object(app, "utcnow", return_value=self.sent - timedelta(hours=3)):
            await app.enqueue_user(101, "test_user")

    async def asyncTearDown(self):
        app._conn.close()
        app._conn = None
        self.bot_patch.stop()
        self.path_patch.stop()
        self.tmp.cleanup()

    async def deliver(self, user_id=101, sent=None):
        with patch.object(app, "utcnow", return_value=sent or self.sent):
            await app.send_step(user_id, 2)



class DiscountTests(DatabaseTestCase):
    async def test_no_discount_before_successful_delivery(self):
        with patch.object(app, "utcnow", return_value=self.sent - timedelta(hours=2)):
            self.assertEqual(await app.get_current_price(101), app.FULL_PRICE)
        row = await app.db_fetchone("SELECT discount_until FROM users WHERE user_id=101")
        self.assertIsNone(row[0])

    async def test_hour_boundaries_through_actual_purchase_handler(self):
        await self.deliver()
        for elapsed, expected in [
            (0, app.DISCOUNT_PRICE),
            (3599, app.DISCOUNT_PRICE),
            (3599.999999, app.DISCOUNT_PRICE),
            (3600, app.FULL_PRICE),
            (3600.000001, app.FULL_PRICE),
            (7200, app.FULL_PRICE),
        ]:
            with self.subTest(elapsed=elapsed):
                callback = SimpleNamespace(
                    from_user=SimpleNamespace(id=101),
                    message=SimpleNamespace(answer=AsyncMock()),
                    answer=AsyncMock(),
                )
                with patch.object(app, "utcnow", return_value=self.sent + timedelta(seconds=elapsed)):
                    await app.pay_cb(callback)
                callback.message.answer.assert_awaited_once_with(
                    app.payment_message(expected), reply_markup=app.kb_pay_with_receipt(expected)
                )
                callback.answer.assert_awaited_once()

    async def test_delivery_preserves_photos_button_and_atomic_state(self):
        async def check_before_return(**kwargs):
            row = await app.db_fetchone("SELECT discount_until FROM users WHERE user_id=101")
            self.assertIsNone(row[0])
        self.fake_bot.send_message.side_effect = check_before_return
        await self.deliver()
        media = self.fake_bot.send_media_group.await_args.kwargs["media"]
        self.assertEqual([photo.media for photo in media], app.STEP2_PHOTOS)
        self.fake_bot.send_message.assert_awaited_once_with(
            chat_id=101, text=app.text_2, reply_markup=app.kb_action("купить", "pay")
        )
        deadline = (await app.db_fetchone("SELECT discount_until FROM users WHERE user_id=101"))[0]
        sent_at = (await app.db_fetchone("SELECT sent_at FROM queue WHERE user_id=101 AND step=2"))[0]
        self.assertEqual(deadline, self.sent.timestamp() + 3600)
        self.assertEqual(sent_at, self.sent.timestamp())

    async def test_failed_text_or_photos_do_not_start_discount(self):
        for method in [self.fake_bot.send_media_group, self.fake_bot.send_message]:
            with self.subTest(method=method):
                method.side_effect = RuntimeError("Simulated delivery failure")
                with self.assertRaises(RuntimeError):
                    await self.deliver()
                self.assertIsNone((await app.db_fetchone(
                    "SELECT discount_until FROM users WHERE user_id=101"
                ))[0])
                self.assertIsNone((await app.db_fetchone(
                    "SELECT sent_at FROM queue WHERE user_id=101 AND step=2"
                ))[0])
                method.side_effect = None
        await self.deliver(sent=self.sent + timedelta(minutes=15))
        deadline = (await app.db_fetchone("SELECT discount_until FROM users WHERE user_id=101"))[0]
        self.assertEqual(deadline, (self.sent + timedelta(minutes=75)).timestamp())

    async def test_discount_persists_after_database_reopen(self):
        await self.deliver()
        app._conn.close()
        await app.db_init()
        for elapsed, expected in [(3599.9, app.DISCOUNT_PRICE), (3600, app.FULL_PRICE)]:
            with patch.object(app, "utcnow", return_value=self.sent + timedelta(seconds=elapsed)):
                self.assertEqual(await app.get_current_price(101), expected)

    async def test_each_user_has_independent_delivery_time(self):
        await app.enqueue_user(202, "second_user")
        await self.deliver()
        await self.deliver(202, self.sent + timedelta(minutes=30))
        with patch.object(app, "utcnow", return_value=self.sent + timedelta(hours=1)):
            self.assertEqual(await app.get_current_price(101), app.FULL_PRICE)
            self.assertEqual(await app.get_current_price(202), app.DISCOUNT_PRICE)

    async def test_queue_worker_marks_sent_only_after_success(self):
        qid = (await app.db_fetchone(
            "SELECT id FROM queue WHERE user_id=101 AND step=2"
        ))[0]
        async def check_pending(**kwargs):
            self.assertIsNone((await app.db_fetchone(
                "SELECT sent_at FROM queue WHERE id=?", (qid,)
            ))[0])
        self.fake_bot.send_message.side_effect = check_pending
        with patch.object(app, "utcnow", return_value=self.sent), patch.object(
            app.asyncio, "sleep", side_effect=asyncio.CancelledError
        ):
            with self.assertRaises(asyncio.CancelledError):
                await app.queue_worker()
        self.assertEqual((await app.db_fetchone(
            "SELECT sent_at FROM queue WHERE id=?", (qid,)
        ))[0], self.sent.timestamp())

    async def test_queue_worker_keeps_failed_delivery_pending(self):
        self.fake_bot.send_message.side_effect = RuntimeError("Simulated failure")
        with patch.object(app, "utcnow", return_value=self.sent), patch.object(
            app.asyncio, "sleep", side_effect=asyncio.CancelledError
        ):
            with self.assertRaises(asyncio.CancelledError):
                await app.queue_worker()
        self.assertIsNone((await app.db_fetchone(
            "SELECT sent_at FROM queue WHERE user_id=101 AND step=2"
        ))[0])
        self.assertIsNone((await app.db_fetchone(
            "SELECT discount_until FROM users WHERE user_id=101"
        ))[0])

    async def test_legacy_pending_deadline_is_cleared_without_new_schema(self):
        await app.db_exec("UPDATE users SET discount_until=? WHERE user_id=101", (self.sent.timestamp(),))
        await app.db_exec(
            "INSERT INTO queue(user_id, step, run_at) VALUES(101, 99, 0)"
        )
        app._conn.close()
        await app.db_init()
        self.assertIsNone((await app.db_fetchone("SELECT discount_until FROM users WHERE user_id=101"))[0])
        columns = [row[1] for row in app._conn.execute("PRAGMA table_info(users)")]
        self.assertEqual(columns, ["user_id", "username", "started_at", "paid", "discount_until", "awaiting_receipt", "receipt_received_at"])
        self.assertEqual((await app.db_fetchone("SELECT COUNT(*) FROM queue WHERE user_id=101"))[0], 10)

    async def test_paid_user_is_not_sent_offer(self):
        await app.confirm_purchase(101)
        await self.deliver()
        self.fake_bot.send_message.assert_not_awaited()
        self.fake_bot.send_media_group.assert_not_awaited()

    async def test_unknown_user_gets_full_price(self):
        self.assertEqual(await app.get_current_price(999), app.FULL_PRICE)

    async def test_start_still_sends_original_video_and_caption(self):
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=303, username="new_user"),
            answer_video=AsyncMock(), answer=AsyncMock(),
        )
        await app.start(message)
        message.answer_video.assert_awaited_once_with(video=app.VIDEO_FILE_ID, caption=app.text_1)
        message.answer.assert_not_awaited()
        self.assertIsNone((await app.db_fetchone("SELECT discount_until FROM users WHERE user_id=303"))[0])
    async def test_status_is_admin_only(self):
        message = SimpleNamespace(from_user=SimpleNamespace(id=101), answer=AsyncMock())
        await app.status_cmd(message)
        message.answer.assert_not_awaited()

    async def test_status_shows_mode_and_live_discount(self):
        admin = app.ADMIN_IDS[0]
        await app.enqueue_user(admin, "test_admin")
        await self.deliver(admin)
        message = SimpleNamespace(from_user=SimpleNamespace(id=admin), answer=AsyncMock())
        with patch.object(app, "utcnow", return_value=self.sent + timedelta(seconds=5)):
            await app.status_cmd(message)
        text = message.answer.await_args.args[0]
        self.assertIn("Бот работает", text)
        self.assertIn("тестовый" if app.TEST_MODE else "обычный", text)
        expected = app.discount_duration(admin) - 5
        self.assertIn(f"осталось {expected:.1f} сек.", text)
        telegram_text(text)



class TestModeTests(DiscountTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.mode_patch = patch.object(app, "TEST_MODE", True)
        self.mode_patch.start()

    async def asyncTearDown(self):
        self.mode_patch.stop()
        await super().asyncTearDown()

    async def test_admin_messages_use_ten_seconds_and_discount_one_minute(self):
        admin = app.ADMIN_IDS[0]
        with patch.object(app, "utcnow", return_value=self.sent):
            await app.enqueue_user(admin, "test_admin")
        schedule = await app.db_fetchall(
            "SELECT run_at FROM queue WHERE user_id=? ORDER BY step", (admin,)
        )
        self.assertEqual([row[0] for row in schedule], [int(self.sent.timestamp()) + 10 * i for i in range(1, 10)])
        await self.deliver(admin)
        for elapsed, expected in [(59.999999, app.DISCOUNT_PRICE), (60, app.FULL_PRICE), (60.000001, app.FULL_PRICE)]:
            with patch.object(app, "utcnow", return_value=self.sent + timedelta(seconds=elapsed)):
                self.assertEqual(await app.get_current_price(admin), expected)
                callback = SimpleNamespace(
                    from_user=SimpleNamespace(id=admin),
                    message=SimpleNamespace(answer=AsyncMock()), answer=AsyncMock(),
                )
                await app.pay_cb(callback)
                callback.message.answer.assert_awaited_once_with(
                    app.payment_message(expected), reply_markup=app.kb_pay_with_receipt(expected)
                )
        self.assertEqual((await app.db_fetchone(
            "SELECT discount_until FROM users WHERE user_id=?", (admin,)
        ))[0], self.sent.timestamp() + 60)
        app._conn.close()
        await app.db_init()
        with patch.object(app, "TEST_MODE", False):
            for elapsed, expected in [(59.999999, app.DISCOUNT_PRICE), (60, app.FULL_PRICE)]:
                with patch.object(app, "utcnow", return_value=self.sent + timedelta(seconds=elapsed)):
                    self.assertEqual(await app.get_current_price(admin), expected)

    async def test_normal_mode_restores_original_schedule_for_admin(self):
        admin = app.ADMIN_IDS[0]
        with patch.object(app, "TEST_MODE", False):
            schedule = app.build_schedule(self.sent, user_id=admin)
            self.assertEqual(schedule[0][1], int(self.sent.timestamp()) + 40 * 60)
            self.assertEqual(schedule[1][1] - schedule[0][1], 24 * 3600)
            self.assertEqual(schedule[2][1] - schedule[1][1], 48 * 3600)
            self.assertEqual(app.discount_duration(admin), 3600)

    async def test_non_admin_keeps_normal_schedule_in_test_mode(self):
        schedule = app.build_schedule(self.sent, user_id=101)
        self.assertEqual(schedule[0][1], int(self.sent.timestamp()) + 40 * 60)
        self.assertEqual(schedule[1][1] - schedule[0][1], 24 * 3600)
        self.assertEqual(app.discount_duration(101), 3600)


class ModeCommandTests(DatabaseTestCase):
    async def test_admin_can_switch_both_modes_and_restart_keeps_choice(self):
        admin = app.ADMIN_IDS[0]
        for command, enabled in [("/test_on", True), ("/test_off", False)]:
            message = SimpleNamespace(from_user=SimpleNamespace(id=admin), text=command, answer=AsyncMock())
            before_users = await app.db_fetchall("SELECT * FROM users")
            before_queue = await app.db_fetchall("SELECT * FROM queue")
            await app.test_mode_cmd(message)
            self.assertEqual(app.TEST_MODE, enabled)
            self.assertEqual(app.get_test_mode(app._conn), enabled)
            app._conn.close()
            await app.db_init()
            self.assertEqual(app.TEST_MODE, enabled)
            self.assertEqual(app.discount_duration(admin), 60 if enabled else 3600)
            self.assertEqual(await app.db_fetchall("SELECT * FROM users"), before_users)
            self.assertEqual(await app.db_fetchall("SELECT * FROM queue"), before_queue)
            message.answer.assert_awaited_once()

    async def test_non_admin_cannot_switch_mode(self):
        message = SimpleNamespace(from_user=SimpleNamespace(id=101), text="/test_on", answer=AsyncMock())
        before = app.TEST_MODE
        await app.test_mode_cmd(message)
        self.assertEqual(app.TEST_MODE, before)
        self.assertEqual(app.get_test_mode(app._conn), before)
        message.answer.assert_not_awaited()


class StatisticsTests(DatabaseTestCase):
    async def test_reset_starts_period_without_changing_users_or_queue(self):
        await app.confirm_purchase(101)
        before_users = await app.db_fetchall("SELECT * FROM users")
        before_queue = await app.db_fetchall("SELECT * FROM queue")
        admin_message = SimpleNamespace(from_user=SimpleNamespace(id=app.ADMIN_IDS[0]), answer=AsyncMock())
        with patch.object(app, "utcnow", return_value=self.sent + timedelta(days=30)):
            await app.reset_stats_cmd(admin_message)
        snapshot = app.get_stats(app._conn)
        self.assertEqual(snapshot[1:3], (0, 0))
        self.assertEqual(await app.db_fetchall("SELECT * FROM users"), before_users)
        self.assertEqual(await app.db_fetchall("SELECT * FROM queue"), before_queue)
        app._conn.close()
        await app.db_init()
        self.assertEqual(app.get_stats(app._conn), snapshot)

    async def test_new_users_and_receipts_count_from_fractional_boundary(self):
        app.reset_stats(app._conn, self.sent.timestamp())
        with patch.object(app, "utcnow", return_value=self.sent + timedelta(microseconds=1)):
            await app.enqueue_user(202, "new")
            await app.confirm_purchase(202)
        self.assertEqual(app.get_stats(app._conn)[1:], (1, 1, 0, 2))
        await app.set_awaiting_receipt(101, 1)
        app.reset_stats(app._conn, (self.sent + timedelta(seconds=1)).timestamp())
        self.assertEqual(app.get_stats(app._conn)[1:], (0, 0, 1, 2))

    async def test_non_admin_cannot_read_or_reset_stats(self):
        message = SimpleNamespace(from_user=SimpleNamespace(id=101), answer=AsyncMock())
        before = app.get_stats(app._conn)
        await app.reset_stats_cmd(message)
        await app.stats_cmd(message)
        message.answer.assert_not_awaited()
        self.assertEqual(app.get_stats(app._conn), before)

    async def test_stats_and_status_show_same_actual_counts(self):
        await app.confirm_purchase(101)
        message = SimpleNamespace(from_user=SimpleNamespace(id=app.ADMIN_IDS[0]), answer=AsyncMock())
        await app.stats_cmd(message)
        stats_text = message.answer.await_args.args[0]
        self.assertIn('Получено чеков за период: <b>1</b>', stats_text)
        self.assertIn('Начали воронку за период: <b>1</b>', stats_text)
        await app.status_cmd(message)
        self.assertIn(stats_text, message.answer.await_args.args[0])
        telegram_text(message.answer.await_args.args[0])


if __name__ == "__main__":
    unittest.main()

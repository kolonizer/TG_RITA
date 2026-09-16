import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.methods import SendMessage

from test_bot import DatabaseTestCase, app, telegram_text, temporary_connection_error


def message(user_id=101, message_id=800):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id, username="test_user", full_name="Test <&> person"),
        chat=SimpleNamespace(id=user_id), message_id=message_id,
        photo=[SimpleNamespace(file_id="receipt_photo")],
        document=SimpleNamespace(file_id="receipt_document"), answer=AsyncMock(),
    )


def callback(message_id, text=None):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=101), answer=AsyncMock(),
        message=SimpleNamespace(message_id=message_id, text=text,
                                from_user=SimpleNamespace(id=123456789), chat=SimpleNamespace(id=101),
                                answer=AsyncMock(return_value=SimpleNamespace(message_id=message_id))),
    )


class ReceiptReliabilityTests(DatabaseTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.fake_bot.send_photo = AsyncMock()
        self.fake_bot.send_document = AsyncMock()
        await self.deliver()
        with patch.object(app, "utcnow", return_value=self.sent):
            await app.pay_cb(callback(701))
            await app.send_receipt_cb(callback(701))

    async def upload(self, kind="photo", now=None, source=None):
        source = source or message()
        with patch.object(app, "utcnow", return_value=now or self.sent + timedelta(hours=2)):
            await (app.receipt_photo(source) if kind == "photo" else app.receipt_document(source))
        return source

    async def test_all_admin_failures_retain_receipt_without_confirming_then_restart_delivers(self):
        self.fake_bot.send_photo.side_effect = RuntimeError("offline")
        source = await self.upload()
        self.assertFalse(await app.is_paid(101))
        self.assertTrue(await app.is_awaiting_receipt(101))
        self.assertIn("Чек сохранён", source.answer.await_args.args[0])
        rows = await app.db_fetchall("SELECT file_id, sent_at, caption FROM receipt_deliveries")
        self.assertEqual(len(rows), len(app.ADMIN_IDS))
        self.assertTrue(all(row[0] == "receipt_photo" and row[1] is None for row in rows))
        self.assertTrue(all("2 333 ₽ / 3 888 ₽" in row[2] for row in rows))
        uploaded_at = (await app.db_fetchone("SELECT receipt_received_at FROM users WHERE user_id=101"))[0]
        app._conn.close()
        await app.db_init()
        self.fake_bot.send_photo.side_effect = None
        with patch.object(app, "utcnow", return_value=self.sent + timedelta(hours=2, seconds=30)):
            for (delivery_id,) in await app.get_due_receipts():
                await app.process_receipt_delivery(delivery_id)
        self.assertTrue(await app.is_paid(101))
        self.assertFalse(await app.is_awaiting_receipt(101))
        self.assertEqual((await app.db_fetchone("SELECT receipt_received_at FROM users WHERE user_id=101"))[0], uploaded_at)
        self.assertEqual(app.get_stats(app._conn)[2], 1)
        self.assertEqual((await app.db_fetchone("SELECT COUNT(*) FROM receipt_deliveries WHERE sent_at IS NULL"))[0], 0)

    async def test_one_failed_admin_does_not_repeat_delivery_to_successful_admin(self):
        async def send(admin_id, **kwargs):
            if admin_id == app.ADMIN_IDS[0]:
                raise RuntimeError("offline")
        self.fake_bot.send_photo.side_effect = send
        await self.upload()
        self.assertTrue(await app.is_paid(101))
        self.fake_bot.send_photo.reset_mock(side_effect=True)
        app._conn.close()
        await app.db_init()
        with patch.object(app, "utcnow", return_value=self.sent + timedelta(hours=3)):
            for (delivery_id,) in await app.get_due_receipts():
                await app.process_receipt_delivery(delivery_id)
        self.fake_bot.send_photo.assert_awaited_once()
        self.assertEqual(self.fake_bot.send_photo.await_args.args[0], app.ADMIN_IDS[0])

    async def test_document_uses_same_durable_forwarding_and_original_prices(self):
        self.fake_bot.send_document.side_effect = RuntimeError("offline")
        await self.upload(kind="document")
        self.assertFalse(await app.is_paid(101))
        rows = await app.db_fetchall("SELECT kind, file_id, caption FROM receipt_deliveries")
        self.assertTrue(all(row[0:2] == ("document", "receipt_document") for row in rows))
        self.assertTrue(all("2 333 ₽ / 3 888 ₽" in row[2] for row in rows))

    async def test_user_fields_are_escaped_and_caption_fits_telegram(self):
        source = message()
        source.from_user.full_name = "<script>&" * 100
        source.from_user.username = "<&>" * 100
        await self.upload(source=source)
        caption = self.fake_bot.send_photo.await_args.kwargs["caption"]
        plain = telegram_text(caption)
        self.assertIn(source.from_user.full_name[:120], plain)
        self.assertLessEqual(len(plain.encode("utf-16-le")) // 2, 1024)

    async def test_repeat_of_same_update_does_not_duplicate_outbox_or_received_count(self):
        self.fake_bot.send_photo.side_effect = RuntimeError("offline")
        source = message()
        await self.upload(source=source)
        await self.upload(source=source)
        self.assertEqual((await app.db_fetchone("SELECT COUNT(*) FROM receipt_deliveries"))[0], len(app.ADMIN_IDS))
        self.assertEqual(self.fake_bot.send_photo.await_count, len(app.ADMIN_IDS))
        self.assertEqual(app.get_stats(app._conn)[2], 1)

    async def test_handler_and_worker_cannot_forward_same_receipt_concurrently(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def slow_send(*args, **kwargs):
            started.set()
            await release.wait()
        self.fake_bot.send_photo.side_effect = slow_send
        with patch.object(app, "utcnow", return_value=self.sent):
            task = asyncio.create_task(app.receipt_photo(message()))
            try:
                await asyncio.wait_for(started.wait(), timeout=1)
                ids = await app.db_fetchall("SELECT id FROM receipt_deliveries")
                await asyncio.gather(*(app.process_receipt_delivery(row[0]) for row in ids))
                self.assertEqual(self.fake_bot.send_photo.await_count, len(app.ADMIN_IDS))
            finally:
                release.set()
                await task

    async def test_pending_receipt_pauses_only_its_users_funnel(self):
        self.fake_bot.send_photo.side_effect = RuntimeError("offline")
        await self.upload()
        with patch.object(app, "utcnow", return_value=self.sent):
            await app.enqueue_user(202, "healthy")
        with patch.object(app, "utcnow", return_value=self.sent + timedelta(days=10)):
            self.assertEqual([row[1] for row in await app.get_due_queue_items()], [202])

    async def test_delivery_of_old_receipt_does_not_confirm_new_funnel_after_reset(self):
        self.fake_bot.send_photo.side_effect = RuntimeError("offline")
        await self.upload()
        await app.reset_user_db(101)
        with patch.object(app, "utcnow", return_value=self.sent + timedelta(days=1)):
            await app.enqueue_user(101, "restarted")
            self.fake_bot.send_photo.side_effect = None
            for (delivery_id,) in await app.get_due_receipts():
                await app.process_receipt_delivery(delivery_id)
        self.assertFalse(await app.is_paid(101))
        self.assertEqual((await app.db_fetchone("SELECT COUNT(*) FROM queue WHERE user_id=101 AND cancelled_at IS NOT NULL"))[0], 0)
        self.assertEqual((await app.db_fetchone("SELECT COUNT(*) FROM receipt_deliveries"))[0], len(app.ADMIN_IDS))

    async def test_expired_discount_and_new_quote_do_not_change_old_payment_message_tariff(self):
        with patch.object(app, "utcnow", return_value=self.sent + timedelta(hours=2)):
            await app.pay_cb(callback(702))
            await app.send_receipt_cb(callback(701))
        app._conn.close()
        await app.db_init()
        await self.upload()
        self.assertIn("2 333 ₽ / 3 888 ₽", self.fake_bot.send_photo.await_args.kwargs["caption"])
        rows = await app.db_fetchall("SELECT message_id, price_without, price_with FROM payment_quotes ORDER BY message_id")
        self.assertEqual(rows, [(701, 2333, 3888), (702, 3333, 5555)])

    async def test_full_price_quote_is_preserved_for_receipt(self):
        with patch.object(app, "utcnow", return_value=self.sent + timedelta(hours=2)):
            await app.pay_cb(callback(702))
            await app.send_receipt_cb(callback(702))
        await self.upload()
        self.assertIn("3 333 ₽ / 5 555 ₽", self.fake_bot.send_photo.await_args.kwargs["caption"])

    async def test_legacy_payment_message_recovers_original_quote(self):
        await app.db_exec("DELETE FROM payment_quotes")
        with patch.object(app, "utcnow", return_value=self.sent + timedelta(hours=2)):
            await app.send_receipt_cb(callback(701, telegram_text(app.payment_message(app.DISCOUNT_PRICE))))
        await self.upload()
        self.assertIn("2 333 ₽ / 3 888 ₽", self.fake_bot.send_photo.await_args.kwargs["caption"])

    async def test_unknown_legacy_tariff_is_not_replaced_with_current_price(self):
        await app.db_exec("DELETE FROM payment_quotes")
        await app.send_receipt_cb(callback(999))
        await self.upload()
        self.assertIn("Тариф ранее не зафиксирован", self.fake_bot.send_photo.await_args.kwargs["caption"])

    async def test_forwarded_payment_message_cannot_create_another_users_discount_quote(self):
        source = callback(999, telegram_text(app.payment_message(app.DISCOUNT_PRICE)))
        source.message.from_user.id = 202
        source.message.forward_origin = object()
        await app.send_receipt_cb(source)
        self.assertIsNone(app.receipts.receipt_prices(app._conn, 101))

    async def test_same_message_id_in_other_chat_does_not_select_private_quote(self):
        source = callback(701)
        source.message.chat.id = -100123
        await app.send_receipt_cb(source)
        self.assertIsNone(app.receipts.receipt_prices(app._conn, 101))

    async def test_forbidden_admin_is_deferred_and_other_admin_receives(self):
        async def send(admin_id, **kwargs):
            if admin_id == app.ADMIN_IDS[0]:
                raise app.TelegramForbiddenError(method=SendMessage(chat_id=admin_id, text="test"), message="blocked")
        self.fake_bot.send_photo.side_effect = send
        await self.upload()
        self.assertTrue(await app.is_paid(101))
        row = await app.db_fetchone("SELECT retry_at, last_error FROM receipt_deliveries WHERE admin_id=?", (app.ADMIN_IDS[0],))
        self.assertEqual(row, (self.sent.timestamp() + 3 * 3600, "TelegramForbiddenError"))

    async def test_receipt_storage_failure_rolls_back_and_does_not_claim_receipt_saved(self):
        await app.db_exec("""CREATE TRIGGER fail_receipt BEFORE INSERT ON receipt_deliveries
            BEGIN SELECT RAISE(ABORT, 'simulated storage failure'); END""")
        source = await self.upload()
        self.assertIn("Не удалось сохранить чек", source.answer.await_args.args[0])
        self.assertEqual((await app.db_fetchone("SELECT COUNT(*) FROM receipt_deliveries"))[0], 0)
        self.assertFalse(await app.is_paid(101))
        self.assertTrue(await app.is_awaiting_receipt(101))
        self.fake_bot.send_photo.assert_not_awaited()

    async def test_receipt_checkpoint_failure_keeps_payload_retryable_without_handler_crash(self):
        await app.db_exec("""CREATE TRIGGER fail_receipt_checkpoint BEFORE UPDATE OF sent_at ON receipt_deliveries
            WHEN NEW.sent_at IS NOT NULL BEGIN SELECT RAISE(ABORT, 'simulated commit failure'); END""")
        source = await self.upload()
        self.assertIn("Чек сохранён", source.answer.await_args.args[0])
        self.assertFalse(await app.is_paid(101))
        self.assertEqual((await app.db_fetchone("SELECT COUNT(*) FROM receipt_deliveries WHERE sending_at IS NULL AND sent_at IS NULL"))[0], len(app.ADMIN_IDS))
        await app.db_exec("DROP TRIGGER fail_receipt_checkpoint")
        with patch.object(app, "utcnow", return_value=self.sent + timedelta(hours=2, seconds=30)):
            for (delivery_id,) in await app.get_due_receipts():
                await app.process_receipt_delivery(delivery_id)
        self.assertTrue(await app.is_paid(101))

    async def test_stale_receipt_claim_expires_without_restart(self):
        self.fake_bot.send_photo.side_effect = RuntimeError("offline")
        await self.upload()
        await app.db_exec("UPDATE receipt_deliveries SET sending_at=?, retry_at=NULL", (self.sent.timestamp(),))
        self.fake_bot.send_photo.side_effect = None
        with patch.object(app, "utcnow", return_value=self.sent + timedelta(seconds=59)):
            self.assertEqual(await app.get_due_receipts(), [])
        with patch.object(app, "utcnow", return_value=self.sent + timedelta(seconds=60)):
            for (delivery_id,) in await app.get_due_receipts():
                await app.process_receipt_delivery(delivery_id)
        self.assertTrue(await app.is_paid(101))

    async def test_old_receipt_cannot_confirm_reset_funnel_even_with_identical_start_timestamp(self):
        self.fake_bot.send_photo.side_effect = RuntimeError("offline")
        await self.upload()
        old_start = (await app.db_fetchone("SELECT started_at FROM users WHERE user_id=101"))[0]
        await app.reset_user_db(101)
        with patch.object(app, "utcnow", return_value=app.datetime.fromtimestamp(old_start, tz=app.timezone.utc)):
            await app.enqueue_user(101, "restarted")
        self.fake_bot.send_photo.side_effect = None
        with patch.object(app, "utcnow", return_value=self.sent + timedelta(hours=3)):
            for (delivery_id,) in await app.get_due_receipts():
                await app.process_receipt_delivery(delivery_id)
        self.assertFalse(await app.is_paid(101))

    async def test_lost_quote_db_write_recovers_from_original_payment_message(self):
        await app.db_exec("""CREATE TRIGGER fail_quote BEFORE INSERT ON payment_quotes
            BEGIN SELECT RAISE(ABORT, 'simulated quote failure'); END""")
        source = callback(703)
        with patch.object(app, "utcnow", return_value=self.sent):
            await app.pay_cb(source)
        source.answer.assert_awaited_once()
        await app.db_exec("DROP TRIGGER fail_quote")
        with patch.object(app, "utcnow", return_value=self.sent + timedelta(hours=2)):
            await app.send_receipt_cb(callback(703, telegram_text(app.payment_message(app.DISCOUNT_PRICE))))
        await self.upload()
        self.assertIn("2 333 ₽ / 3 888 ₽", self.fake_bot.send_photo.await_args.kwargs["caption"])

    async def test_receipt_send_timeout_defers_without_confirming_or_sticking_claim(self):
        async def hang(*args, **kwargs):
            await asyncio.Event().wait()
        self.fake_bot.send_photo.side_effect = hang
        with patch.object(app, "QUEUE_SEND_TIMEOUT", 0.01):
            await self.upload()
        self.assertFalse(await app.is_paid(101))
        self.assertEqual((await app.db_fetchone("SELECT COUNT(*) FROM receipt_deliveries WHERE sending_at IS NULL AND retry_at IS NOT NULL"))[0], len(app.ADMIN_IDS))

    async def test_worker_resumes_receipt_forwards_without_resending_upload(self):
        self.fake_bot.send_photo.side_effect = RuntimeError("offline")
        await self.upload()
        self.fake_bot.send_photo.side_effect = None
        delivered = asyncio.Event()
        real_finish = app.receipts.finish_delivery
        def finish(*args):
            result = real_finish(*args)
            delivered.set()
            return result
        with patch.object(app, "utcnow", return_value=self.sent + timedelta(hours=3)), patch.object(app.receipts, "finish_delivery", side_effect=finish):
            worker = asyncio.create_task(app.queue_worker())
            try:
                await asyncio.wait_for(delivered.wait(), timeout=1)
                self.assertTrue(await app.is_paid(101))
            finally:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)


class QueueReliabilityTests(DatabaseTestCase):
    async def qid(self):
        return (await app.db_fetchone("SELECT id FROM queue WHERE user_id=101 AND step=2"))[0]

    async def resolve(self, qid, action, now=None, admin=None):
        source = message(user_id=admin or app.ADMIN_IDS[0])
        source.text = f"/resolve_delivery {qid} {action}"
        with patch.object(app, "utcnow", return_value=now or self.sent):
            await app.resolve_delivery_cmd(source)
        return source

    async def test_successful_album_is_not_repeated_after_text_connection_failure_and_restart(self):
        self.fake_bot.send_message.side_effect = temporary_connection_error()
        qid = await self.qid()
        with patch.object(app, "utcnow", return_value=self.sent):
            await app.process_queue_item(qid, 101, 2)
        app._conn.close()
        await app.db_init()
        self.fake_bot.send_message.side_effect = None
        with patch.object(app, "utcnow", return_value=self.sent + timedelta(seconds=30)):
            await app.process_queue_item(qid, 101, 2)
        self.fake_bot.send_media_group.assert_awaited_once()
        self.assertEqual(self.fake_bot.send_message.await_count, 2)
        self.assertEqual((await app.db_fetchone("SELECT discount_until FROM users WHERE user_id=101"))[0], self.sent.timestamp() + 30 + 3600)

    async def test_lost_response_never_replays_ambiguous_album_after_restart(self):
        self.fake_bot.send_media_group.side_effect = app.TelegramNetworkError(method=SendMessage(chat_id=101, text="test"), message="response lost")
        qid = await self.qid()
        with patch.object(app, "utcnow", return_value=self.sent):
            await app.process_queue_item(qid, 101, 2)
        app._conn.close()
        await app.db_init()
        with patch.object(app, "utcnow", return_value=self.sent + timedelta(days=10)):
            self.assertEqual(await app.get_due_queue_items(), [])
        self.fake_bot.send_media_group.assert_awaited_once()
        self.fake_bot.send_message.assert_not_awaited()
        self.assertIn("требующие проверки: 1", await app.delivery_status())

    async def test_admin_can_confirm_album_then_text_sends_without_duplicate_photos(self):
        self.fake_bot.send_media_group.side_effect = RuntimeError("response lost")
        qid = await self.qid()
        with patch.object(app, "utcnow", return_value=self.sent):
            await app.process_queue_item(qid, 101, 2)
        await self.resolve(qid, "media_sent")
        self.fake_bot.send_media_group.side_effect = None
        with patch.object(app, "utcnow", return_value=self.sent):
            await app.process_queue_item(qid, 101, 2)
        self.fake_bot.send_media_group.assert_awaited_once()
        self.fake_bot.send_message.assert_awaited_once()

    async def test_failed_db_commit_after_text_delivery_is_not_replayed_and_can_be_confirmed(self):
        await app.db_exec("""CREATE TRIGGER fail_delivery BEFORE UPDATE OF sent_at ON queue
            WHEN NEW.sent_at IS NOT NULL BEGIN SELECT RAISE(ABORT, 'simulated commit failure'); END""")
        qid = await self.qid()
        with patch.object(app, "utcnow", return_value=self.sent):
            await app.process_queue_item(qid, 101, 2)
        await app.db_exec("DROP TRIGGER fail_delivery")
        app._conn.close()
        await app.db_init()
        with patch.object(app, "utcnow", return_value=self.sent + timedelta(hours=2)):
            self.assertEqual(await app.get_due_queue_items(), [])
        await self.resolve(qid, "sent 2026-09-16T12:00:00.750000Z", now=self.sent + timedelta(minutes=30))
        self.fake_bot.send_message.assert_awaited_once()
        self.assertEqual((await app.db_fetchone("SELECT discount_until FROM users WHERE user_id=101"))[0], self.sent.timestamp() + 3600)

    async def test_payment_callback_recovers_ambiguous_offer_using_telegram_date(self):
        qid = await self.qid()
        await app.db_exec("UPDATE queue SET delivery_phase='text', uncertain_at=? WHERE id=?", (self.sent.timestamp(), qid))
        source = callback(700)
        source.message.text = telegram_text(app.text_2)
        source.message.from_user = SimpleNamespace(id=self.fake_bot.id)
        source.message.chat = SimpleNamespace(id=101)
        source.message.date = self.sent
        with patch.object(app, "utcnow", return_value=self.sent + timedelta(minutes=30)):
            await app.pay_cb(source)
        self.assertIn("2 333 ₽", source.message.answer.await_args.args[0])
        self.assertEqual((await app.db_fetchone("SELECT sent_at FROM queue WHERE id=?", (qid,)))[0], self.sent.timestamp())

    async def test_non_admin_cannot_resolve_uncertain_delivery(self):
        qid = await self.qid()
        await app.db_exec("UPDATE queue SET delivery_phase='text', uncertain_at=? WHERE id=?", (self.sent.timestamp(), qid))
        source = await self.resolve(qid, "retry", admin=202)
        source.answer.assert_not_awaited()
        self.assertIsNotNone((await app.db_fetchone("SELECT uncertain_at FROM queue WHERE id=?", (qid,)))[0])

    async def test_invalid_or_future_confirmation_date_does_not_change_delivery(self):
        qid = await self.qid()
        await app.db_exec("UPDATE queue SET delivery_phase='text', uncertain_at=? WHERE id=?", (self.sent.timestamp(), qid))
        for date in ("garbage", "2027-01-01T00:00:00Z", "2026-09-16T12:00:00"):
            await self.resolve(qid, "sent " + date)
            self.assertIsNotNone((await app.db_fetchone("SELECT uncertain_at FROM queue WHERE id=?", (qid,)))[0])

    async def test_uncertain_delivery_is_visible_even_before_due_date(self):
        qid = await self.qid()
        await app.db_exec("UPDATE queue SET delivery_phase='text', uncertain_at=?, run_at=? WHERE id=?", (self.sent.timestamp(), self.sent.timestamp() + 86400, qid))
        source = message(user_id=app.ADMIN_IDS[0])
        with patch.object(app, "utcnow", return_value=self.sent):
            await app.debug_queue_cmd(source)
        self.assertTrue(any(f"ID={qid}" in call.args[0] for call in source.answer.await_args_list))


class StartReliabilityTests(DatabaseTestCase):
    async def test_start_handler_handles_enqueue_db_failure_and_allows_retry(self):
        source = message(202)
        source.answer_video = AsyncMock()
        await app.db_exec("""CREATE TRIGGER fail_enqueue BEFORE INSERT ON queue
            WHEN NEW.user_id=202 BEGIN SELECT RAISE(ABORT, 'simulated interruption'); END""")
        await app.start(source)
        self.assertFalse(await app.already_started(202))
        self.assertIn("Не удалось сохранить начало", source.answer.await_args.args[0])
        await app.db_exec("DROP TRIGGER fail_enqueue")
        await app.start(source)
        self.assertTrue(await app.already_started(202))

    async def test_interrupted_initial_enqueue_rolls_back_user_and_all_jobs(self):
        await app.db_exec("""CREATE TRIGGER fail_enqueue BEFORE INSERT ON queue
            WHEN NEW.user_id=202 AND NEW.step=4 BEGIN SELECT RAISE(ABORT, 'simulated interruption'); END""")
        with self.assertRaises(app.sqlite3.IntegrityError):
            await app.enqueue_user(202, "new")
        self.assertFalse(await app.already_started(202))
        self.assertEqual((await app.db_fetchone("SELECT COUNT(*) FROM queue WHERE user_id=202"))[0], 0)
        await app.db_exec("DROP TRIGGER fail_enqueue")
        await app.enqueue_user(202, "new")
        self.assertEqual((await app.db_fetchone("SELECT COUNT(*) FROM queue WHERE user_id=202"))[0], 9)

    async def test_failed_replacement_enqueue_retains_previous_complete_funnel(self):
        before_users = await app.db_fetchall("SELECT * FROM users")
        before_queue = await app.db_fetchall("SELECT * FROM queue")
        await app.db_exec("""CREATE TRIGGER fail_enqueue BEFORE INSERT ON queue
            WHEN NEW.step=4 BEGIN SELECT RAISE(ABORT, 'simulated interruption'); END""")
        with self.assertRaises(app.sqlite3.IntegrityError):
            await app.enqueue_user(101, "restarted")
        self.assertEqual(await app.db_fetchall("SELECT * FROM users"), before_users)
        self.assertEqual(await app.db_fetchall("SELECT * FROM queue"), before_queue)

    async def test_two_simultaneous_starts_send_one_video_and_create_one_complete_queue(self):
        first, second = message(202), message(202)
        started, release = asyncio.Event(), asyncio.Event()
        async def video(**kwargs):
            started.set()
            await release.wait()
        first.answer_video = AsyncMock(side_effect=video)
        second.answer_video = AsyncMock()
        tasks = [asyncio.create_task(app.start(first))]
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            tasks.append(asyncio.create_task(app.start(second)))
        finally:
            release.set()
            await asyncio.gather(*tasks)
        first.answer_video.assert_awaited_once()
        second.answer_video.assert_not_awaited()
        self.assertEqual((await app.db_fetchone("SELECT COUNT(*) FROM queue WHERE user_id=202"))[0], 9)

    async def test_restart_repairs_old_untouched_partial_schedule_without_deleting_rows(self):
        original = await app.db_fetchall("SELECT id, step, run_at FROM queue WHERE user_id=101 AND step<=3")
        await app.db_exec("DELETE FROM queue WHERE user_id=101 AND step>3")
        app._conn.close()
        await app.db_init()
        self.assertEqual(await app.db_fetchall("SELECT id, step, run_at FROM queue WHERE user_id=101 AND step<=3"), original)
        self.assertEqual((await app.db_fetchone("SELECT COUNT(*) FROM queue WHERE user_id=101"))[0], 9)

    async def test_ninth_message_matches_twenty_four_day_course(self):
        self.assertIn("24 дня", telegram_text(app.text_9))
        self.assertNotIn("25 дней", telegram_text(app.text_9))

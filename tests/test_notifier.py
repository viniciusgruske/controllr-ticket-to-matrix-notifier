from __future__ import annotations

import os
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs

from main import ControllrLoginScreen, ResultsScreen, SharedLoginScreen, TicketNotifierApp, TicketScreen, category_choices
from textual.containers import ScrollableContainer, VerticalScroll
from textual.widgets import Button, Input, TextArea
from notifier import (
    Category,
    ControllrResponse,
    MatrixSendResponse,
    RoomResult,
    Settings,
    TicketNotifier,
    UserFacingError,
    categories_from_response,
    default_env_file,
)


def settings() -> Settings:
    return Settings(
        controllr_url="https://controllr.example",
        matrix_url="https://matrix.example",
        controllr_username="controllr-user",
        matrix_username="matrix-user",
        use_same_password=True,
        client_id=24096,
        default_category_id=14,
        matrix_rooms={"backbone": ["!one:example", "!two:example"]},
    )


class SettingsTests(unittest.TestCase):
    def test_default_env_file_uses_executable_directory_when_frozen(self) -> None:
        with (
            patch("notifier.sys.frozen", True, create=True),
            patch("notifier.sys.executable", "/opt/ticket-notifier/ticket-notifier"),
        ):
            self.assertEqual(default_env_file(), Path("/opt/ticket-notifier/.env"))

    def test_from_env_parses_values(self) -> None:
        environment = {
            "CONTROLLR_URL": "https://controllr.example/",
            "MATRIX_URL": "https://matrix.example/",
            "CONTROLLR_USERNAME": "controllr",
            "MATRIX_USERNAME": "matrix",
            "USE_SAME_PASSWORD": "false",
            "CLIENT_ID": "24096",
            "DEFAULT_CATEGORY_ID": "14",
            "MATRIX_ROOMS": '{"backbone":["!room:example"]}',
        }
        with patch.dict(os.environ, environment, clear=True):
            loaded = Settings.from_env("/path/that/does/not/exist")

        self.assertFalse(loaded.use_same_password)
        self.assertEqual(loaded.controllr_url, "https://controllr.example")
        self.assertEqual(loaded.matrix_rooms["backbone"], ["!room:example"])

    def test_from_env_rejects_invalid_room_json(self) -> None:
        environment = {
            "CONTROLLR_URL": "https://controllr.example",
            "MATRIX_URL": "https://matrix.example",
            "CONTROLLR_USERNAME": "controllr",
            "MATRIX_USERNAME": "matrix",
            "USE_SAME_PASSWORD": "true",
            "CLIENT_ID": "24096",
            "DEFAULT_CATEGORY_ID": "14",
            "MATRIX_ROOMS": "not-json",
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaises(UserFacingError):
                Settings.from_env("/path/that/does/not/exist")

    def test_from_env_parses_multiline_matrix_rooms(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            loaded = Settings.from_env("tests/fixtures/multiline.env")

        self.assertEqual(loaded.matrix_rooms, {"backbone": ["!one:example", "!two:example"]})


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_ticket_encodes_all_fields(self) -> None:
        @dataclass
        class Response:
            success: bool
            errors: list[object]
            results: list[dict[str, object]]

        class Controllr:
            body = ""

            async def ticket_create(self, body: str) -> ControllrResponse:
                self.body = body
                return Response(True, [], [{"ticket_protocol": "123"}])

            async def support_category_list(self, body: str) -> ControllrResponse:
                return Response(True, [], [])

        controllr = Controllr()
        workflow = TicketNotifier(settings())
        workflow.controllr = controllr

        protocol = await workflow.create_ticket(14, "A & B", "linha 1\nlinha 2", "alto & urgente")

        self.assertEqual(protocol, "123")
        parsed = parse_qs(controllr.body)
        self.assertEqual(parsed["ticket_title"], ["A & B"])
        self.assertEqual(parsed["ticket_desc"], ["linha 1\nlinha 2"])
        self.assertEqual(parsed["ticket_obs"], ["Impacto:\nalto & urgente"])

    async def test_notify_rooms_reports_each_room(self) -> None:
        @dataclass
        class Response:
            event_id: str | None

        @dataclass
        class RoomState:
            events: Sequence[Mapping[str, object]]

        class Matrix:
            def __init__(self) -> None:
                self.messages: list[dict[str, str]] = []

            async def room_send(
                self,
                room_id: str,
                message_type: str,
                content: dict[str, str],
            ) -> MatrixSendResponse:
                self.messages.append(content)
                if room_id == "!one:example":
                    return Response("$event")
                return Response(None)

            async def room_get_state(self, room_id: str) -> RoomState:
                if room_id == "!one:example":
                    return RoomState([{"type": "m.room.name", "content": {"name": "Backbone"}}])
                raise RuntimeError("State unavailable")

            async def close(self) -> None:
                return None

        workflow = TicketNotifier(settings())
        matrix = Matrix()
        workflow.matrix = matrix

        results = await workflow.notify_rooms("backbone", "123", "A & B", "Alto\n<urgente>")

        self.assertEqual([result.success for result in results], [True, False])
        self.assertEqual(results[0].room_id, "!one:example")
        self.assertEqual(results[0].room_name, "Backbone")
        self.assertEqual(results[1].room_name, "!two:example")
        self.assertEqual(matrix.messages[0]["body"], "### 123 - A & B\n*Impacto:* Alto\n<urgente>")
        self.assertEqual(matrix.messages[0]["format"], "org.matrix.custom.html")
        self.assertEqual(
            matrix.messages[0]["formatted_body"],
            "<h3>123 - A &amp; B</h3><p><strong>Impacto:</strong> Alto<br>&lt;urgente&gt;</p>",
        )


    async def test_matrix_login_failure_preserves_controllr_session(self) -> None:
        @dataclass
        class CtrlResponse:
            success: bool
            errors: list[object]
            results: list[dict[str, object]]

        @dataclass
        class AuthFail:
            access_token: None = None

        @dataclass
        class AuthOk:
            access_token: str = "token"

        @dataclass
        class FakeMatrix:
            access_token: str = ""
            async def login(self, password: str, device_name: str = "") -> AuthFail | AuthOk:
                if password == "wrong":
                    return AuthFail()
                return AuthOk()
            async def close(self) -> None:
                return None

        called = 0

        def make_matrix(_url: str, _user: str) -> FakeMatrix:
            nonlocal called
            called += 1
            return FakeMatrix()

        categories_data: list[dict[str, object]] = [{"category_pk": 14, "category_name": "Backbone"}]
        controllr_client = MagicMock()
        controllr_client.support_category_list = AsyncMock(return_value=CtrlResponse(True, [], categories_data))

        workflow = TicketNotifier(settings())
        workflow.controllr = controllr_client  # type: ignore[assignment]

        with patch("notifier.AsyncClient", side_effect=make_matrix):
            with self.assertRaises(UserFacingError) as ctx1:
                await workflow.login_matrix("user", "wrong")
            self.assertNotIn("Autentique no Controllr", str(ctx1.exception))
            self.assertIsNotNone(workflow.controllr)

            categories = await workflow.login_matrix("user", "correct")
            self.assertEqual(len(categories), 1)
            self.assertEqual(categories[0].name, "Backbone")

        self.assertEqual(called, 2)


class LoginScreenTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_palette_is_disabled(self) -> None:
        app = TicketNotifierApp(settings())
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertFalse(app.use_command_palette)

    async def test_shared_login_prefills_both_usernames(self) -> None:
        app = TicketNotifierApp(settings())
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertIsInstance(app.screen, SharedLoginScreen)
            screen = app.screen
            self.assertIsInstance(screen, SharedLoginScreen)
            self.assertEqual(screen.query_one("#controllr-username", Input).value, "controllr-user")
            self.assertEqual(screen.query_one("#matrix-username", Input).value, "matrix-user")

    async def test_separate_login_starts_with_controllr(self) -> None:
        separate_settings = Settings(
            controllr_url="https://controllr.example",
            matrix_url="https://matrix.example",
            controllr_username="controllr-user",
            matrix_username="matrix-user",
            use_same_password=False,
            client_id=24096,
            default_category_id=14,
            matrix_rooms={"backbone": ["!one:example"]},
        )
        app = TicketNotifierApp(separate_settings)
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertIsInstance(app.screen, ControllrLoginScreen)
            screen = app.screen
            self.assertIsInstance(screen, ControllrLoginScreen)
            self.assertEqual(screen.query_one("#username", Input).value, "controllr-user")

    async def test_login_form_has_scroll_when_terminal_short(self) -> None:
        app = TicketNotifierApp(settings())
        async with app.run_test(size=(80, 6)) as pilot:
            await pilot.pause()
            sc = app.screen.query_one(".login-scroll")
            self.assertGreater(sc.max_scroll_y, 0)

    async def test_login_form_centered_when_terminal_tall(self) -> None:
        app = TicketNotifierApp(settings())
        async with app.run_test(size=(80, 40)) as pilot:
            await pilot.pause()
            sc = app.screen.query_one(".login-scroll")
            self.assertEqual(sc.max_scroll_y, 0)


class TicketScreenTests(unittest.IsolatedAsyncioTestCase):
    async def test_ticket_form_scroll_reveals_actions(self) -> None:
        app = TicketNotifierApp(settings())
        ticket_screen = TicketScreen(
            app.notifier,
            [Category(14, "Backbone")],
            app.exit,
            MagicMock(),
        )
        async with app.run_test(size=(80, 10)) as pilot:
            await pilot.pause()
            app.push_screen(ticket_screen)
            await pilot.pause()
            form = ticket_screen.query_one("#ticket-form", VerticalScroll)
            self.assertGreater(form.max_scroll_y, 0)

            form.scroll_end(animate=False)
            await pilot.pause()
            submit = ticket_screen.query_one("#submit", Button)
            self.assertLessEqual(submit.region.bottom, form.region.bottom)

    async def test_submit_reads_selects_without_runtime_generic_check(self) -> None:
        app = TicketNotifierApp(settings())
        show_results = MagicMock()
        ticket_screen = TicketScreen(
            app.notifier,
            [Category(14, "Backbone")],
            app.exit,
            show_results,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            with (
                patch.object(app.notifier, "create_ticket", AsyncMock(return_value="123")) as create_ticket,
                patch.object(app.notifier, "notify_rooms", AsyncMock(return_value=[])) as notify_rooms,
            ):
                app.push_screen(ticket_screen)
                await pilot.pause()
                ticket_screen.query_one("#title", Input).value = "Titulo"
                ticket_screen.query_one("#description", TextArea).text = "Descricao"
                ticket_screen.query_one("#impact", TextArea).text = "Impacto"
                ticket_screen.query_one("#ticket-form", VerticalScroll).scroll_end(animate=False)
                await pilot.pause()

                await pilot.click("#submit")
                await pilot.pause()

        create_ticket.assert_awaited_once_with(14, "Titulo", "Descricao", "Impacto")
        notify_rooms.assert_awaited_once_with("backbone", "123", "Titulo", "Impacto")
        show_results.assert_called_once()


class ResultsScreenTests(unittest.IsolatedAsyncioTestCase):
    async def test_results_scroll_reveals_actions(self) -> None:
        app = TicketNotifierApp(settings())
        results = [RoomResult(f"!room-{index}:example", True, "Mensagem enviada.") for index in range(10)]
        results_screen = ResultsScreen("123", results)
        async with app.run_test(size=(80, 10)) as pilot:
            await pilot.pause()
            app.push_screen(results_screen)
            await pilot.pause()
            results_scroll = results_screen.query_one(".results-scroll", ScrollableContainer)
            self.assertGreater(results_scroll.max_scroll_y, 0)

            results_scroll.scroll_end(animate=False)
            await pilot.pause()
            actions = results_screen.query_one("#result-actions")
            another_button = results_screen.query_one("#another", Button)
            exit_button = results_screen.query_one("#exit", Button)
            self.assertGreater(another_button.region.x, actions.region.x)
            self.assertLessEqual(exit_button.region.bottom, results_scroll.region.bottom)


class CategoryTests(unittest.TestCase):
    def test_category_choices_are_alphabetical(self) -> None:
        categories = [
            Category(2, "zeta"),
            Category(3, "alpha"),
            Category(1, "Backbone"),
        ]

        self.assertEqual(
            category_choices(categories),
            [("alpha", "3"), ("Backbone", "1"), ("zeta", "2")],
        )

    def test_categories_from_response_ignores_invalid_results(self) -> None:
        categories = categories_from_response(
            [
                {"category_pk": "14", "category_name": "Backbone"},
                {"invalid": True},
            ]
        )

        self.assertEqual([(category.identifier, category.name) for category in categories], [(14, "Backbone")])

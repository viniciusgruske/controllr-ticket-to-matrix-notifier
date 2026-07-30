from __future__ import annotations

from typing import Callable, cast

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Header, Input, Label, Select, Static, TextArea

from notifier import Category, RoomResult, Settings, TicketNotifier, UserFacingError


def category_choices(categories: list[Category]) -> list[tuple[str, str]]:
    return [
        (category.name, str(category.identifier))
        for category in sorted(categories, key=lambda category: category.name.casefold())
    ]


class NoticeScreen(ModalScreen[None]):
    def __init__(self, title: str, message: str) -> None:
        super().__init__()
        self.dialog_title = title
        self.message = message

    def compose(self) -> ComposeResult:
        with Container(classes="dialog"):
            yield Label(self.dialog_title, classes="dialog-title")
            yield Static(self.message)
            yield Button("Fechar", variant="primary", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss()


class ControllrLoginScreen(ModalScreen[bool]):
    def __init__(self, notifier: TicketNotifier) -> None:
        super().__init__()
        self.notifier = notifier

    def compose(self) -> ComposeResult:
        with Container(classes="login-screen"):
            with ScrollableContainer(classes="login-scroll"):
                yield Label("Login Controllr", classes="dialog-title login-title")
                yield Label("Username")
                yield Input(value=self.notifier.settings.controllr_username, id="username")
                yield Label("Password")
                yield Input(password=True, id="password")
                yield Static("", id="login-error", classes="error")
                with Container(classes="login-actions"):
                    yield Button("Login", variant="primary", id="login")

    def on_mount(self) -> None:
        self.query_one("#password", Input).focus()

    async def _attempt_login(self) -> None:
        username = self.query_one("#username", Input).value.strip()
        password = self.query_one("#password", Input).value
        self.query_one("#login", Button).disabled = True
        try:
            await self.notifier.login_controllr(username, password)
        except UserFacingError as error:
            self.query_one("#login-error", Static).update(str(error))
            self.query_one("#login", Button).disabled = False
            return
        self.dismiss(True)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.run_worker(self._attempt_login())

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "login":
            return
        await self._attempt_login()


class MatrixLoginScreen(ModalScreen[list[Category] | None]):
    def __init__(self, notifier: TicketNotifier) -> None:
        super().__init__()
        self.notifier = notifier

    def compose(self) -> ComposeResult:
        with Container(classes="login-screen"):
            with ScrollableContainer(classes="login-scroll"):
                yield Label("Login Matrix", classes="dialog-title login-title")
                yield Label("Username")
                yield Input(value=self.notifier.settings.matrix_username, id="username")
                yield Label("Password")
                yield Input(password=True, id="password")
                yield Static("", id="login-error", classes="error")
                with Container(classes="login-actions"):
                    yield Button("Login", variant="primary", id="login")

    def on_mount(self) -> None:
        self.query_one("#password", Input).focus()

    async def _attempt_login(self) -> None:
        username = self.query_one("#username", Input).value.strip()
        password = self.query_one("#password", Input).value
        self.query_one("#login", Button).disabled = True
        try:
            categories = await self.notifier.login_matrix(username, password)
        except UserFacingError as error:
            self.query_one("#login-error", Static).update(str(error))
            self.query_one("#login", Button).disabled = False
            return
        self.dismiss(categories)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.run_worker(self._attempt_login())

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "login":
            return
        await self._attempt_login()


class SharedLoginScreen(ModalScreen[list[Category] | None]):
    def __init__(self, notifier: TicketNotifier) -> None:
        super().__init__()
        self.notifier = notifier

    def compose(self) -> ComposeResult:
        with Container(classes="login-screen"):
            with ScrollableContainer(classes="login-scroll"):
                yield Label("Login Controllr/Matrix", classes="dialog-title login-title")
                yield Label("Username Controllr")
                yield Input(value=self.notifier.settings.controllr_username, id="controllr-username")
                yield Label("Username Matrix")
                yield Input(value=self.notifier.settings.matrix_username, id="matrix-username")
                yield Label("Password")
                yield Input(password=True, id="password")
                yield Static("", id="login-error", classes="error")
                with Container(classes="login-actions"):
                    yield Button("Login", variant="primary", id="login")

    def on_mount(self) -> None:
        self.query_one("#password", Input).focus()

    async def _attempt_login(self) -> None:
        controllr_username = self.query_one("#controllr-username", Input).value.strip()
        matrix_username = self.query_one("#matrix-username", Input).value.strip()
        password = self.query_one("#password", Input).value
        self.query_one("#login", Button).disabled = True
        try:
            await self.notifier.login_controllr(controllr_username, password)
            categories = await self.notifier.login_matrix(matrix_username, password)
        except UserFacingError as error:
            self.query_one("#login-error", Static).update(str(error))
            self.query_one("#login", Button).disabled = False
            return
        self.dismiss(categories)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.run_worker(self._attempt_login())

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "login":
            return
        await self._attempt_login()


class TicketScreen(Screen[None]):
    def __init__(
        self,
        notifier: TicketNotifier,
        categories: list[Category],
        exit_app: Callable[[], None],
        show_results: Callable[[str, list[RoomResult], Callable[[bool | None], None]], None],
    ) -> None:
        super().__init__()
        self.notifier = notifier
        self.categories = categories
        self.exit_app = exit_app
        self.show_results = show_results

    def compose(self) -> ComposeResult:
        category_options = category_choices(self.categories)
        default_id = str(self.notifier.settings.default_category_id)
        selected_id = default_id if any(value == default_id for _, value in category_options) else category_options[0][1]
        room_options: list[tuple[str, str]] = [
            (group, group) for group in self.notifier.settings.matrix_rooms
        ]
        with VerticalScroll(id="ticket-form"):
            yield Label("Novo ticket", id="form-title")
            yield Label("Categoria")
            yield Select[str](category_options, value=selected_id, allow_blank=False, id="category")
            yield Label("Titulo")
            yield Input(placeholder="Titulo do ticket", id="title")
            yield Label("Descricao")
            yield TextArea(placeholder="Descricao do ticket", id="description")
            yield Label("Impacto")
            yield TextArea(placeholder="Impacto", id="impact")
            yield Label("Grupo de salas Matrix")
            yield Select[str](room_options, allow_blank=False, id="room-group")
            yield Static("", id="form-error", classes="error")
            with Horizontal(id="ticket-actions"):
                yield Button("Criar ticket e notificar", variant="primary", id="submit")
                yield Button("Sair", id="exit")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "exit":
            self.exit_app()
            return
        if event.button.id != "submit":
            return

        category = cast(Select[str], self.query_one("#category", Select)).value
        group = cast(Select[str], self.query_one("#room-group", Select)).value
        title = self.query_one("#title", Input).value.strip()
        description = self.query_one("#description", TextArea).text.strip()
        impact = self.query_one("#impact", TextArea).text.strip()
        if not title or not description or not impact or not isinstance(category, str) or not isinstance(group, str):
            self.query_one("#form-error", Static).update("Preencha todos os campos.")
            return

        event.button.disabled = True
        self.query_one("#form-error", Static).update("")
        try:
            protocol = await self.notifier.create_ticket(int(category), title, description, impact)
        except UserFacingError as error:
            self.query_one("#form-error", Static).update(str(error))
            event.button.disabled = False
            return

        results = await self.notifier.notify_rooms(group, protocol, title, impact)
        self.show_results(protocol, results, self._after_results)
        event.button.disabled = False

    def _after_results(self, open_another: bool | None) -> None:
        if open_another:
            self.query_one("#title", Input).value = ""
            self.query_one("#description", TextArea).clear()
            self.query_one("#impact", TextArea).clear()
            self.query_one("#form-error", Static).update("")
        else:
            self.exit_app()


class ResultsScreen(ModalScreen[bool]):
    def __init__(self, protocol: str, results: list[RoomResult]) -> None:
        super().__init__()
        self.protocol = protocol
        self.results = results

    def compose(self) -> ComposeResult:
        with Container(classes="results-screen"):
            with ScrollableContainer(classes="results-scroll"):
                yield Label(f"Ticket {self.protocol} criado", classes="dialog-title login-title")
                for result in self.results:
                    status = "Sucesso" if result.success else "Erro"
                    yield Static(f"[{status}] {result.room_name or result.room_id}: {result.detail}")
                with Horizontal(id="result-actions"):
                    yield Button("Abrir outro", variant="primary", id="another")
                    yield Button("Sair", id="exit")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "another")


class TicketNotifierApp(App[None]):
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { align: center middle; background: $surface; }
    .login-screen, .results-screen { width: 100%; height: 100%; align: center middle; background: $surface; }
    .login-scroll, .results-scroll { width: 70; max-width: 100%; max-height: 100%; overflow-x: auto; overflow-y: auto; background: $surface; padding: 1 2; }
    #ticket-form { width: 90%; height: 100%; padding: 1 3 2 3; }
    #ticket-actions { height: 4; align: center middle; }
    #result-actions { height: 4; align: center middle; }
    #form-title { text-style: bold; text-align: center; margin-bottom: 1; }
    TextArea { height: 8; margin-bottom: 1; }
    Select, Input { margin-bottom: 1; }
    .dialog { width: 70; max-height: 80%; padding: 1 2; border: thick $accent; background: $surface; }
    .dialog-title { text-style: bold; margin-bottom: 1; }
    .login-title { text-align: center; }
    .login-actions { height: auto; align: center middle; }
    .error { color: $error; margin: 1 0; }
    Button { margin: 1 1 0 0; }
    """
    BINDINGS = [("ctrl+c", "quit", "Sair")]

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.notifier = TicketNotifier(settings)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()

    def on_mount(self) -> None:
        if self.notifier.settings.use_same_password:
            self.push_screen(SharedLoginScreen(self.notifier), self._after_login)
        else:
            self.push_screen(ControllrLoginScreen(self.notifier), self._after_controllr_login)

    def _after_controllr_login(self, logged_in: bool | None) -> None:
        if not logged_in:
            self.exit()
            return
        self.push_screen(MatrixLoginScreen(self.notifier), self._after_login)

    def _after_login(self, categories: list[Category] | None) -> None:
        if categories is None:
            self.exit()
            return
        self.push_screen(TicketScreen(self.notifier, categories, self.exit, self._show_results))

    def _show_results(
        self,
        protocol: str,
        results: list[RoomResult],
        callback: Callable[[bool | None], None],
    ) -> None:
        self.push_screen(ResultsScreen(protocol, results), callback)

    async def on_unmount(self) -> None:
        await self.notifier.close()


def main() -> None:
    try:
        settings = Settings.from_env()
    except UserFacingError as error:
        print(f"Erro de configuracao: {error}")
        return
    TicketNotifierApp(settings).run()


if __name__ == "__main__":
    main()

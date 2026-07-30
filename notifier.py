"""Configuration and API workflow for the ticket notifier."""

from __future__ import annotations

import json
import os
import sys
from base64 import b64encode
from dataclasses import dataclass
from html import escape
from io import StringIO
from pathlib import Path
from typing import Mapping, Protocol, Sequence, cast
from urllib.parse import urlencode

from dotenv import dotenv_values
from nio import AsyncClient

from brbyteapi.controllr import AsyncControllr


PROJECT_ROOT = Path(__file__).resolve().parent


def default_env_file() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().with_name(".env")
    return PROJECT_ROOT / ".env"


class UserFacingError(Exception):
    """An expected error whose message can be shown directly in the TUI."""


@dataclass(frozen=True)
class Settings:
    controllr_url: str
    matrix_url: str
    controllr_username: str
    matrix_username: str
    use_same_password: bool
    client_id: int
    default_category_id: int
    matrix_rooms: dict[str, list[str]]

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> "Settings":
        file_values, matrix_rooms_from_file = read_env_file(env_file or default_env_file())
        required = (
            "CONTROLLR_URL",
            "MATRIX_URL",
            "CONTROLLR_USERNAME",
            "MATRIX_USERNAME",
            "USE_SAME_PASSWORD",
            "CLIENT_ID",
            "DEFAULT_CATEGORY_ID",
            "MATRIX_ROOMS",
        )
        values = {
            key: os.getenv(key, file_values.get(key, "")).strip()
            for key in required
            if key != "MATRIX_ROOMS"
        }
        matrix_rooms_value: object = os.getenv("MATRIX_ROOMS", matrix_rooms_from_file)
        if isinstance(matrix_rooms_value, str):
            try:
                matrix_rooms_value = json.loads(matrix_rooms_value)
            except json.JSONDecodeError as error:
                raise UserFacingError("MATRIX_ROOMS deve conter um objeto JSON valido.") from error
        values["MATRIX_ROOMS"] = "configured" if matrix_rooms_value is not None else ""
        missing = [key for key, value in values.items() if not value]
        if missing:
            raise UserFacingError(f"Variaveis ausentes no .env: {', '.join(missing)}")

        matrix_rooms = validate_matrix_rooms(matrix_rooms_value)
        if matrix_rooms is None:
            raise UserFacingError("MATRIX_ROOMS deve ser um objeto de grupos com listas de salas.")

        boolean_values = {"true": True, "false": False}
        same_password = boolean_values.get(values["USE_SAME_PASSWORD"].lower())
        if same_password is None:
            raise UserFacingError("USE_SAME_PASSWORD deve ser true ou false.")

        try:
            return cls(
                controllr_url=values["CONTROLLR_URL"].rstrip("/"),
                matrix_url=values["MATRIX_URL"].rstrip("/"),
                controllr_username=values["CONTROLLR_USERNAME"],
                matrix_username=values["MATRIX_USERNAME"],
                use_same_password=same_password,
                client_id=int(values["CLIENT_ID"]),
                default_category_id=int(values["DEFAULT_CATEGORY_ID"]),
                matrix_rooms=matrix_rooms,
            )
        except ValueError as error:
            raise UserFacingError("CLIENT_ID e DEFAULT_CATEGORY_ID devem ser numeros inteiros.") from error


def read_env_file(env_file: str | Path) -> tuple[dict[str, str], object | None]:
    """Read dotenv values while allowing MATRIX_ROOMS to be multiline JSON."""
    path = Path(env_file)
    if not path.is_file():
        return {}, None

    source = path.read_text(encoding="utf-8")
    declaration = "MATRIX_ROOMS="
    start = source.find(declaration)
    matrix_rooms: object | None = None
    if start >= 0:
        value_start = start + len(declaration)
        raw_value = source[value_start:].lstrip()
        leading_whitespace = len(source[value_start:]) - len(raw_value)
        try:
            matrix_rooms, value_end = json.JSONDecoder().raw_decode(raw_value)
        except json.JSONDecodeError as error:
            raise UserFacingError("MATRIX_ROOMS deve conter um objeto JSON valido.") from error
        source = source[:start] + source[value_start + leading_whitespace + value_end :]

    parsed = dotenv_values(stream=StringIO(source))
    values = {key: value for key, value in parsed.items() if value is not None}
    return values, matrix_rooms


def validate_matrix_rooms(value: object) -> dict[str, list[str]] | None:
    if not isinstance(value, dict):
        return None
    rooms_by_group: dict[str, list[str]] = {}
    raw_rooms_by_group = cast(dict[object, object], value)
    for group, rooms in raw_rooms_by_group.items():
        if not isinstance(group, str) or not isinstance(rooms, list):
            return None
        raw_rooms = cast(list[object], rooms)
        typed_rooms = [room for room in raw_rooms if isinstance(room, str) and room]
        if len(typed_rooms) != len(raw_rooms):
            return None
        rooms_by_group[group] = typed_rooms
    return rooms_by_group


@dataclass(frozen=True)
class Category:
    identifier: int
    name: str


@dataclass(frozen=True)
class RoomResult:
    room_id: str
    success: bool
    detail: str
    room_name: str | None = None


class ControllrResponse(Protocol):
    @property
    def success(self) -> bool: ...

    @property
    def errors(self) -> Sequence[object]: ...

    @property
    def results(self) -> Sequence[Mapping[str, object]]: ...


class ControllrClient(Protocol):
    async def support_category_list(self, body: str) -> ControllrResponse: ...

    async def ticket_create(self, body: str) -> ControllrResponse: ...


class MatrixSendResponse(Protocol):
    event_id: str | None


class MatrixRoomStateResponse(Protocol):
    events: Sequence[Mapping[str, object]]


class MatrixClient(Protocol):
    async def room_send(
        self,
        room_id: str,
        message_type: str,
        content: dict[str, str],
    ) -> MatrixSendResponse: ...

    async def room_get_state(self, room_id: str) -> MatrixRoomStateResponse: ...

    async def close(self) -> None: ...


def categories_from_response(results: Sequence[Mapping[str, object]]) -> list[Category]:
    categories: list[Category] = []
    for result in results:
        identifier = result.get("category_pk", result.get("support_category_pk"))
        name = result.get("category_name", result.get("support_category_name", result.get("name")))
        if not isinstance(identifier, (int, str)) or not isinstance(name, str):
            continue
        try:
            categories.append(Category(int(identifier), str(name)))
        except (TypeError, ValueError):
            continue
    return categories


def response_errors(response: ControllrResponse) -> str:
    messages: list[str] = []
    for error in response.errors:
        if isinstance(error, Mapping):
            typed_error = cast(Mapping[str, object], error)
            messages.append(str(typed_error.get("msg", typed_error)))
        else:
            messages.append(str(error))
    return "; ".join(messages) or "A API nao informou detalhes do erro."


def matrix_message_content(protocol: str, title: str, impact: str) -> dict[str, str]:
    body = f"### {protocol} - {title}\n*Impacto:* {impact}"
    formatted_impact = escape(impact).replace("\n", "<br>")
    return {
        "msgtype": "m.text",
        "body": body,
        "format": "org.matrix.custom.html",
        "formatted_body": (
            f"<h3>{escape(protocol)} - {escape(title)}</h3>"
            f"<p><strong>Impacto:</strong> {formatted_impact}</p>"
        ),
    }


class TicketNotifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.controllr: ControllrClient | None = None
        self.matrix: MatrixClient | None = None

    async def login_controllr(self, username: str, password: str) -> None:
        if not username or not password:
            raise UserFacingError("Usuario e senha do Controllr sao obrigatorios.")
        successful_login = await AsyncControllr.login(
            self.settings.controllr_url,
            username,
            password,
        )
        if not successful_login:
            raise UserFacingError("Nao foi possivel autenticar no Controllr.")

        authorization = b64encode(
            f"{username}:{password}".encode("utf-8")
        ).decode("utf-8")
        self.controllr = cast(
            ControllrClient,
            AsyncControllr(f"Basic {authorization}", self.settings.controllr_url, 30),
        )

    async def login_matrix(self, username: str, password: str) -> list[Category]:
        if self.controllr is None:
            raise UserFacingError("Autentique no Controllr antes de entrar no Matrix.")
        if not username or not password:
            raise UserFacingError("Usuario e senha do Matrix sao obrigatorios.")

        matrix = AsyncClient(self.settings.matrix_url, username)
        matrix_response = await matrix.login(password, device_name="Ticket notifier")
        if not getattr(matrix_response, "access_token", None):
            await matrix.close()
            raise UserFacingError(f"Nao foi possivel autenticar no Matrix: {matrix_response}")
        self.matrix = cast(MatrixClient, matrix)

        category_response = await self.controllr.support_category_list("")
        if not category_response.success:
            raise UserFacingError(f"Nao foi possivel carregar categorias: {response_errors(category_response)}")
        categories = categories_from_response(category_response.results)
        if not categories:
            raise UserFacingError("O Controllr nao retornou categorias validas.")
        return categories

    async def create_ticket(
        self, category_id: int, title: str, description: str, impact: str
    ) -> str:
        if self.controllr is None:
            raise UserFacingError("A sessao do Controllr nao esta autenticada.")
        body = urlencode(
            {
                "client_pk": self.settings.client_id,
                "category_pk": category_id,
                "topic_pk": 0,
                "ticket_sla": 0,
                "ticket_priority": 10,
                "ticket_title": title,
                "ticket_desc": description,
                "ticket_obs": f"Impacto:\n{impact}",
            }
        )
        response = await self.controllr.ticket_create(body)
        if not response.success:
            raise UserFacingError(f"Nao foi possivel criar o ticket: {response_errors(response)}")
        result: Mapping[str, object] = response.results[0] if response.results else {}
        protocol = result.get("ticket_protocol")
        if protocol is None:
            protocol = result.get("protocol")
        if not protocol:
            raise UserFacingError("Ticket criado, mas a API nao retornou o protocolo para notificacao.")
        return str(protocol)

    async def notify_rooms(self, group: str, protocol: str, title: str, impact: str) -> list[RoomResult]:
        if self.matrix is None:
            raise UserFacingError("A sessao Matrix nao esta autenticada.")
        message = matrix_message_content(protocol, title, impact)
        results: list[RoomResult] = []
        for room_id in self.settings.matrix_rooms[group]:
            room_name = await self._room_name(room_id)
            try:
                response = await self.matrix.room_send(
                    room_id,
                    message_type="m.room.message",
                    content=message,
                )
                if getattr(response, "event_id", None):
                    results.append(RoomResult(room_id, True, "Mensagem enviada.", room_name))
                else:
                    results.append(RoomResult(room_id, False, str(response), room_name))
            except Exception as error:
                results.append(RoomResult(room_id, False, str(error), room_name))
        return results

    async def _room_name(self, room_id: str) -> str:
        if self.matrix is None:
            return room_id
        try:
            response = await self.matrix.room_get_state(room_id)
        except Exception:
            return room_id
        for event in response.events:
            if event.get("type") != "m.room.name":
                continue
            content = event.get("content")
            if not isinstance(content, Mapping):
                continue
            name = cast(Mapping[str, object], content).get("name")
            if isinstance(name, str) and name:
                return name
        return room_id

    async def close(self) -> None:
        if self.matrix is not None:
            await self.matrix.close()
            self.matrix = None

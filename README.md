# controllr-ticket-to-matrix-notifier

TUI for opening tickets in Controllr and notifying Matrix room groups using the user running the script.

## Configuration

Fill in the local `.env` file. It is ignored by Git; `.env.example` documents the accepted values.

System environment variables take precedence over values defined in `.env`.

| Variable | Description | Expected value | Example |
| --- | --- | --- | --- |
| `CONTROLLR_URL` | Base URL of the Controllr instance used to create tickets. A trailing slash is optional. | HTTP or HTTPS URL | `https://controllr.example.com:8443` |
| `MATRIX_URL` | Base URL of the Matrix homeserver used to send notifications. A trailing slash is optional. | HTTP or HTTPS URL | `https://matrix.example.com` |
| `CONTROLLR_USERNAME` | Username used to authenticate with Controllr. | Non-empty text | `john.doe` |
| `MATRIX_USERNAME` | Username used to authenticate with Matrix. | Non-empty text | `@john:example.com` |
| `USE_SAME_PASSWORD` | Controls whether one password entry is used for both services. | `true` or `false` | `true` |
| `CLIENT_ID` | Numeric Controllr client identifier used when opening tickets. | Integer | `24096` |
| `DEFAULT_CATEGORY_ID` | Numeric Controllr category identifier preselected in the ticket form. | Integer | `14` |
| `MATRIX_ROOMS` | JSON object mapping a room-group name displayed in the TUI to Matrix room IDs or aliases. | JSON object with arrays of non-empty strings | See below |

When `USE_SAME_PASSWORD=true`, the same password entered in the TUI is used for Controllr and Matrix. When it is `false`, the application asks for each password separately. Passwords are never stored in `.env`.

`MATRIX_ROOMS` may span multiple lines:

```env
MATRIX_ROOMS={
  "backbone": ["!room1:wsinternet.com.br"],
  "clients": ["#room:wsinternet.com.br"]
}
```

## Running

```bash
.venv/bin/python main.py
```

Use `Ctrl+V` in the title, description, and impact fields to paste text.

## Distribution

Releases include a single executable for Linux and another for Windows. Extract the appropriate file, copy `.env.example` to `.env` in the same directory as the executable, and fill in the configuration values.

```bash
cp .env.example .env
./ticket-notifier
```

On Windows, run `ticket-notifier.exe` from Explorer or PowerShell. The `.env` file is looked up next to the executable, regardless of the directory from which it is started.

## Building the Executable

The build produces a `--onefile` package for the current operating system:

```bash
.venv/bin/python -m pip install -r requirements-build.txt
.venv/bin/python scripts/build.py
```

The resulting `.zip` file is placed in `release/`. To build for Windows and Linux, run the `Build release packages` workflow on a `v*` tag; it uses native runners for each platform.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The project also requires strict static analysis:

```bash
.venv/bin/pyright
```

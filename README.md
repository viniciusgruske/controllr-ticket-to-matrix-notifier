# controllr-ticket-to-matrix-notifier

TUI for opening tickets in Controllr and notifying Matrix room groups using the user running the script.

## Configuration

Fill in the local `.env` file. It is ignored by Git; `.env.example` documents the accepted values.

`MATRIX_ROOMS` must be a JSON object that maps the name displayed in the TUI to a list of room IDs or aliases. The JSON may span multiple lines:

```env
MATRIX_ROOMS={
  "backbone": ["!room1:wsinternet.com.br"],
  "clients": ["#room:wsinternet.com.br"]
}
```

With `USE_SAME_PASSWORD=true`, the same password entered in the TUI is used for Controllr and Matrix. Passwords are never stored in `.env`.

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

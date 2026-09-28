# Repository Guidelines

## Project Structure & Module Organization

Zviber is a PyQt5 desktop floating panel (calendar + todo) for Windows 7/10/11, Python 3.8+. Flat layout, one responsibility per module:

- `main.pyw` — entry point: single instance (QLocalServer IPC), system tray, `--toggle` flag
- `app.py` also hosts `SettingsDialog` — frameless settings window (gear button), styles live in each theme's QSS under `#settingsPanel`
- `app.py` — panel UI: calendar/todo tabs, dual-column mode, dragging, DPI scaling
- `calendar_data.py` — embedded official holiday/make-up-workday data, lunar calendar, online/offline updates
- `themes.py` — three QSS themes with `%CN%`/`%NUM%` font placeholders
- `sysutil.py` — registry integration: autostart + desktop context menu (HKCU, no admin)
- `install.py` — one-time installer (`--remove` to uninstall)
- `designs/` — theme mockups (HTML/PNG) and `designs/verify/` self-check screenshots

Runtime data lives in `%APPDATA%\ZviberPanel\` (`config.json`, `todos.json`, `holidays.json`) — never commit it.

## Build, Test, and Development Commands

```bat
pip install PyQt5            :: only dependency (pin "PyQt5==5.15.*" for Win7)
pythonw main.pyw             :: run the panel
python install.py            :: install context menu + autostart
python install.py --remove   :: uninstall
set ZVIBER_SHOT=designs\verify && python main.pyw   :: visual self-check
```

The self-check exports screenshots for both themes (dark/light) x calendar/todo/dual views, then exits. Run it after any UI or theme change. Screenshots are git-ignored — never commit them.

## Coding Style & Naming Conventions

- 4-space indent, `# -*- coding: utf-8 -*-` header on every module
- Match existing style: `snake_case` functions, `UPPER_SNAKE` constants, single-quote strings, `%`-formatting
- Module docstrings and inline comments are in Chinese — keep it that way
- No external linter/formatter; keep diffs minimal and consistent with surrounding code

## Testing Guidelines

No unit-test framework. Verification is the `ZVIBER_SHOT` screenshot self-check plus manual checks of tray menu, context-menu toggle, and autostart. Confirm behavior on scaled DPI (125%/150%) when touching layout code.

## Commit & Pull Request Guidelines

Repo: [github.com/evachxji/zviber](https://github.com/evachxji/zviber) (public, MIT). Use conventional prefixes (`feat:`, `fix:`, `refactor:`) with a short Chinese or English summary. PRs should include: what changed and why, self-check screenshots for visual changes, and the Windows/Python versions tested.

## Security & Configuration Tips

- Registry writes stay under HKCU — never require admin rights
- Network access is limited to the timor.tech holiday API; keep the offline JSON import path working for intranet users

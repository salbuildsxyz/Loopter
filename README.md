# LOOPTER

A small Windows app that recognizes battle royale menu screens and, if you allow it, presses **Play** and **Play Again** for you.

![LOOP's main screen](docs/screenshot.png)

## Features

- **Demo, Monitor, and Interact modes.** Try it on a built-in demo window, watch your screen without sending any input, or opt in to clicking.
- **Guided setup.** Capture a screenshot, confirm the button LOOP suggests, and test recognition right away.
- **Careful clicking.** Clicks only land in the focused game window, wait while you're using the mouse, and stop if the screen doesn't change.
- **Emergency stop.** A global shortcut (`Ctrl+Shift+F12` by default) stops everything instantly.
- **Activity log.** See every detection, near miss, and click as it happens.
- **Local only.** No network access, no telemetry.

## Download

Grab `LOOP-<version>-windows.zip` from the [latest release](https://github.com/salbuildsxyz/Loopter/releases). The build isn't code-signed, so Windows SmartScreen may warn you the first time.

## Setup

1. Extract the zip anywhere and run `LOOP.exe`.
2. Leave the mode on **Demo** and press **Start session** to see how it works.
3. Open **Setup**, capture your own Play and Play Again buttons, then switch to **Monitor** to check that LOOP recognizes them.

## Disclaimer

LOOP is an unofficial, independent project and isn't affiliated with or endorsed by Epic Games or any other game publisher. Automating input in an online game may break its terms of service and could get your account restricted or banned. LOOP doesn't touch game memory or anti-cheat, and it isn't undetectable. Use it at your own risk.

## License

[MIT](LICENSE)

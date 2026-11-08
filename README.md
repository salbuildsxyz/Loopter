# Loopt

A small Windows app I made that automatically clicks **Play** and **Play Again** between Fortnite matches. It also has Auto Walk, a Treasure Tracker, and optional Discord notifications.

<img width="1087" height="607" alt="Screenshot 2026-11-08 085151" src="https://github.com/user-attachments/assets/f33efecf-4ce8-4c17-b95e-b8cf47f01a4b" />

## Features

- Automatically detects and clicks Play and Play Again
- Auto Walk that starts when you're in a match
- Experimental Treasure Tracker that watches for 6 different rewards
- Optional Discord notifications when a reward is detected
- Simple dark UI
- Custom button setup if detection isn't working
- Activity logs and diagnostics
- Emergency stop (`Ctrl+Shift+F12`)
- Saves your settings between launches

## Download

Get the latest version from [Releases](https://github.com/salbuildsxyz/Loopter/releases).

Download `Loopt-0.3.1-windows.zip`, extract the entire ZIP, open the `Loopt` folder, and run `Loopt.exe`.

Windows might show a SmartScreen warning since the app isn't digitally signed.

## How to use

1. Open Loopt and select your Fortnite window.
2. Set up your Play and Play Again buttons in the **Setup** tab if needed.
3. Click **Start auto click** and confirm.
4. To use Auto Walk, start it from the Home tab. It waits until you're in a match before walking.
5. For reward tracking, go to the **Treasures** tab. You can also connect Discord for notifications.

You can turn off any features you don't want to use.

## Notes

- Treasure Tracker is still experimental, and not every reward has been verified in live gameplay.
- Auto Walk uses the game's health bar to tell when you're in a match, so it might not work with custom or hidden HUD layouts.
- Discord notifications require connecting your Discord account.
- Loopt runs locally for monitoring and detection. Discord features use an online service when enabled.

## Disclaimer

Loopt isn't affiliated with Epic Games. Game automation may violate their rules and put your account at risk. Use it at your own discretion.

## License

[MIT](LICENSE)

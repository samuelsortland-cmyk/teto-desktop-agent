# Teto for Chromebook ♪

Teto on your Chromebook: she chats in Chrome's **side panel**, walks around on your **web pages**, and works **in the tabs you already have open**, even while you use another tab.

This is separate from Teto for Windows. Nothing here changes or updates the Windows app.

## How it fits together

- **Teto's brain** runs in your Chromebook's **Linux** side. It uses your Claude Pro/Max sign-in through Claude Code.
- **Her body** is the **Teto for Chromebook** Chrome extension: the side-panel chat, the pixel Teto on your pages, and the hands that work in your tabs.
- The two talk over `localhost`. ChromeOS forwards it to Linux automatically. Every request carries a secret token that only your copy of the extension has.

## Install (one time, ~5 minutes)

1. **Turn on Linux:** Settings → About ChromeOS → Developers → *Linux development environment* → Set up.
2. **Install Teto:** open the **Terminal** app and paste:
   ```
   curl -fsSL https://raw.githubusercontent.com/samuelsortland-cmyk/teto-desktop-agent/main/chromebook/install.sh | bash
   ```
3. **Add her to Chrome:** go to `chrome://extensions` and turn on **Developer mode**. Click **Load unpacked**, open **Linux files → teto → chromebook → extension**, and click **Select**. Pin **Teto for Chromebook** from the puzzle-piece menu.
4. Click her icon. The chat opens on the side. Click **Sign in**, sign in with your Claude account, and you're set.

After a restart, Linux may be asleep. Open the **Teto** app from your launcher (or the Terminal) and she wakes up.

> School-managed Chromebooks often block Linux and developer-mode extensions. If step 1 or 3 is greyed out, your school's admin has turned it off.

## What she can do

| | Chromebook |
|---|---|
| Chat (side panel, same look as Windows) with quick replies | ✅ |
| Work **inside your existing tabs** (quizzes, forms, email...) without switching to them | ✅ |
| No new tabs unless you ask | ✅ (enforced) |
| Type into Google Docs and other editors | ✅ |
| Open new tabs, sites and searches when you ask | ✅ |
| Eagle Eyes for the tab you're on (browser games, canvas pages): she sees it and clicks/presses keys in it | ✅ |
| Pixel Teto walking on your pages: idle tricks, drag & fling with gravity, speech bubbles, reacts while working | ✅ |
| Full permission, speed, model settings | ✅ |
| Runs Linux commands (files, info) | ✅ (in the Linux container) |
| Updates herself (Chromebook copy only) | ✅ |
| Control the ChromeOS desktop, Files app, settings or **Android apps / Roblox app** | ❌ ChromeOS doesn't allow this from Linux or extensions |

## Files

- `install.sh`: the installer (Linux side). It sets up a background service and the **Teto** launcher app.
- `teto_cb/`: the Linux program. It reuses Teto's brain and tab tools from `../teto`.
- `extension/`: the Chrome extension (side panel, on-page pet, tab commands).
- `tools/build_sprites.py`: renders Teto's frames from `teto/sprites.py` into `extension/sprites/`.
- `tests/`: `python -m pytest chromebook/tests`. Includes a real end-to-end run of the extension in Chromium.

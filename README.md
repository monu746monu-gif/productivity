# Vexa

Vexa is a macOS voice productivity assistant. It can track app usage, save todos, ideas, and reminders, and compare today's productivity with yesterday.

## User Setup

1. Install the Vexa app from the `.dmg`.
2. Open Vexa from the menu bar icon.
3. If Vexa is connected to the hosted backend, it is ready immediately.
4. If Vexa is running in local mode, paste an OpenAI API key in Settings.
5. Allow macOS permissions when prompted:
   - Microphone, for voice commands.
   - Accessibility, for active app tracking.

In hosted mode, your OpenAI API key stays on the hosted backend and is never shipped in the app. In local mode, the OpenAI API key is saved on the Mac at `~/.vexa/config.json`.

## Developer Build

Install frontend dependencies:

```bash
npm install
```

Create the backend virtual environment and install Python dependencies:

```bash
cd backend
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cd ..
```

Run the development app:

```bash
npm run tauri dev
```

Build a macOS app bundle:

```bash
npm run tauri build
```

The built app appears under:

```bash
src-tauri/target/release/bundle/
```

## Hosted Backend Build

Set the backend URL when building the downloadable app:

```bash
VITE_API_BASE_URL=https://your-vexa-api.example.com npm run tauri build
```

Or copy `.env.production.example` to `.env.production` and set `VITE_API_BASE_URL` there.

The hosted backend should have:

```bash
OPENAI_API_KEY=your_server_side_key
```

Do not put your OpenAI API key in the Tauri app. Desktop app bundles can be inspected by users.

## Notes For Testers

The app now records audio locally and sends it to the configured backend. For public use, host the backend and build the app with `VITE_API_BASE_URL`.

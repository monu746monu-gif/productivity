import { listen } from "@tauri-apps/api/event";
import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE_URL, apiUrl } from "./api";
import "./App.css";

const VOICE_RECORD_MS = 4000;

type VoiceCommandResponse = {
  transcript?: string;
  reply?: string;
  missing_api_key?: boolean;
};

function isTauriApp() {
  return "__TAURI_INTERNALS__" in window;
}

async function readVoiceCommandResponse(res: Response) {
  let data: any = {};

  try {
    data = await res.json();
  } catch {
    data = {};
  }

  if (!res.ok) {
    throw new Error(data.detail || data.error || "Vexa backend could not process voice.");
  }

  if (data.missing_api_key) {
    throw new Error("Vexa is not configured with the server API key yet.");
  }

  return data as VoiceCommandResponse;
}

async function recordVoiceClip(durationMs = VOICE_RECORD_MS) {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    throw new Error("Audio recording is not supported on this device.");
  }

  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const chunks: BlobPart[] = [];
  const mimeType = MediaRecorder.isTypeSupported("audio/webm")
    ? "audio/webm"
    : "";
  const recorder = new MediaRecorder(
    stream,
    mimeType ? { mimeType } : undefined,
  );

  return new Promise<Blob>((resolve, reject) => {
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        chunks.push(event.data);
      }
    };

    recorder.onerror = () => {
      stream.getTracks().forEach((track) => track.stop());
      reject(new Error("Could not record audio."));
    };

    recorder.onstop = () => {
      stream.getTracks().forEach((track) => track.stop());
      resolve(new Blob(chunks, { type: mimeType || "audio/webm" }));
    };

    recorder.start();
    window.setTimeout(() => {
      if (recorder.state !== "inactive") {
        recorder.stop();
      }
    }, durationMs);
  });
}

async function sendBrowserVoiceCommand() {
  const audio = await recordVoiceClip();
  const formData = new FormData();
  formData.append("file", audio, "voice.webm");

  const res = await fetch(apiUrl("/voice-command-audio"), {
    method: "POST",
    body: formData,
  });

  return readVoiceCommandResponse(res);
}

async function sendNativeVoiceCommand() {
  const res = await fetch(apiUrl("/voice-command"), {
    method: "POST",
  });

  return readVoiceCommandResponse(res);
}

async function sendVoiceCommand() {
  if (isTauriApp()) {
    return sendNativeVoiceCommand();
  }

  return sendBrowserVoiceCommand();
}

function MainApp() {
  const [status, setStatus] = useState("Sleeping...");
  const [reply, setReply] = useState("Say Hey Vexa, or tap the voice button.");
  const [isListening, setIsListening] = useState(false);
  const [dashboard, setDashboard] = useState<any>(null);
  const [dueReminder, setDueReminder] = useState<any>(null);
  const [apiKeyConfigured, setApiKeyConfigured] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsMessage, setSettingsMessage] = useState("");
  const isListeningRef = useRef(false);
  const continuousConversationRef = useRef(false);
  const listeningRunIdRef = useRef(0);
  const startListeningRef = useRef<(continuous?: boolean) => void>(() => {});

  const speak = useCallback((text: string) => {
    const utterance = new SpeechSynthesisUtterance(text);

    const voices = window.speechSynthesis.getVoices();

    const selectedVoice =
      voices.find((v) => v.name.includes("Samantha")) ||
      voices.find((v) => v.name.includes("Victoria")) ||
      voices.find((v) => v.lang.includes("en"));

    if (selectedVoice) {
      utterance.voice = selectedVoice;
    }

    utterance.rate = 1.02;
    utterance.pitch = 1.04;
    utterance.volume = 1;

    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);

    utterance.onend = () => {
      setStatus("Sleeping...");

      if (continuousConversationRef.current) {
        window.setTimeout(() => {
          startListeningRef.current(true);
        }, 350);
      }
    };
  }, []);

  const loadDashboard = useCallback(async (showStatus = false) => {
    try {
      if (showStatus) {
        setStatus("Refreshing...");
      }

      const res = await fetch(apiUrl("/dashboard"));
      const data = await res.json();
      setDashboard(data);

      if (showStatus) {
        setStatus("Sleeping...");
        setReply("Dashboard refreshed.");
      }
    } catch (error) {
      console.error(error);

      if (showStatus) {
        setStatus("Error");
        setReply("Dashboard backend is not running.");
      }
    }
  }, []);

  const loadSettings = useCallback(async () => {
    try {
      const res = await fetch(apiUrl("/settings"));
      const data = await res.json();
      const configured = Boolean(data.openai_api_key_configured);

      setApiKeyConfigured(configured);
      setSettingsOpen(false);

      if (!configured) {
        setReply("Vexa is not configured with the server API key yet.");
      }
    } catch (error) {
      console.error(error);
      setSettingsOpen(false);
      setSettingsMessage("Backend is not running yet.");
    }
  }, []);

  const checkDueReminders = useCallback(async () => {
    try {
      const res = await fetch(apiUrl("/reminders/due"));
      const data = await res.json();
      const reminders = data.reminders || [];

      if (!reminders.length) {
        return;
      }

      const title = reminders.map((reminder: any) => reminder.title).join(", ");
      const reminderText =
        reminders.length === 1
          ? `Reminder, Monu: ${title}`
          : `Reminders, Monu: ${title}`;

      setDueReminder({
        title,
        display_time: reminders[0].display_time,
      });
      setStatus("Reminder");
      setReply(reminderText);
      speak(reminderText);
      loadDashboard();
    } catch (error) {
      console.error(error);
    }
  }, [loadDashboard, speak]);

  const startListening = useCallback(async (continuous = true) => {
    if (!apiKeyConfigured) {
      continuousConversationRef.current = false;
      setSettingsOpen(false);
      setReply("Vexa is not configured with the server API key yet.");
      return;
    }

    if (isListeningRef.current) {
      return;
    }

    try {
      continuousConversationRef.current = continuous;
      isListeningRef.current = true;
      const runId = listeningRunIdRef.current + 1;
      listeningRunIdRef.current = runId;
      setIsListening(true);
      setStatus("Listening...");
      setReply("I'm listening.");

      const data = await sendVoiceCommand();

      if (runId !== listeningRunIdRef.current) {
        return;
      }

      const transcript = String(data.transcript || "").toLowerCase();
      const shouldStop =
        transcript.includes("stop listening") ||
        transcript.includes("stop conversation") ||
        transcript.includes("go to sleep") ||
        transcript.includes("sleep now");

      if (shouldStop) {
        continuousConversationRef.current = false;
      }

      setStatus("Speaking...");
      setReply(shouldStop ? "Okay Monu, I will stop listening." : data.reply || "Done.");
      speak(shouldStop ? "Okay Monu, I will stop listening." : data.reply || "Done.");
      loadDashboard();
    } catch (error) {
      console.error(error);
      continuousConversationRef.current = false;
      setStatus("Error");
      setReply(error instanceof Error ? error.message : "Vexa voice command failed.");
    } finally {
      setIsListening(false);
      isListeningRef.current = false;
    }
  }, [apiKeyConfigured, loadDashboard, speak]);

  useEffect(() => {
    startListeningRef.current = startListening;
  }, [startListening]);

  useEffect(() => {
    loadSettings();
    loadDashboard();
    checkDueReminders();

    const interval = setInterval(() => {
      loadDashboard();
      checkDueReminders();
    }, 10000);

    return () => clearInterval(interval);
  }, [checkDueReminders, loadDashboard, loadSettings]);

  useEffect(() => {
    let unlistenStart: (() => void) | undefined;
    let unlistenStop: (() => void) | undefined;

    listen("vexa-start-listening", () => {
      if (!apiKeyConfigured) {
        setSettingsOpen(false);
        setReply("Vexa is not configured with the server API key yet.");
        return;
      }

      if (isListeningRef.current || continuousConversationRef.current) {
        return;
      }

      continuousConversationRef.current = true;
      setStatus("Speaking...");
      setReply("Hey, what's up?");
      speak("Hey, what's up?");
    }).then((cleanup) => {
      unlistenStart = cleanup;
    });

    listen("vexa-stop-listening", () => {
      continuousConversationRef.current = false;
      listeningRunIdRef.current += 1;
      window.speechSynthesis.cancel();
      setIsListening(false);
      isListeningRef.current = false;
      setStatus("Sleeping...");
      setReply("Sleeping...");
    }).then((cleanup) => {
      unlistenStop = cleanup;
    });

    return () => {
      unlistenStart?.();
      unlistenStop?.();
    };
  }, [apiKeyConfigured, speak]);

  const orbClass =
    status === "Listening..."
      ? "orb listening"
      : status === "Thinking..."
      ? "orb thinking"
      : status === "Speaking..."
      ? "orb speaking"
      : "orb";

  return (
    <main className="app">
      <div className="background-glow glow-one" />
      <div className="background-glow glow-two" />

      {dueReminder && (
        <div className="reminder-popup" role="alert">
          <div>
            <span>Reminder</span>
            <strong>{dueReminder.title}</strong>
            <p>{dueReminder.display_time}</p>
          </div>

          <button onClick={() => setDueReminder(null)}>Dismiss</button>
        </div>
      )}

      <section className="shell">
        <div className="assistant-panel">
          <div className="top-pill">
            <span className="pulse-dot" />
            Voice-first AI companion
          </div>

          <div className={orbClass}>
            <div className="orb-inner">V</div>
          </div>

          <h1>Vexa</h1>
          <p className="subtitle">Your macOS productivity assistant</p>

          {settingsOpen && (
            <div className="settings-card">
              <div>
                <strong>{apiKeyConfigured ? "Connected" : "Not configured"}</strong>
                <p>
                  {apiKeyConfigured
                    ? "Vexa is using the server OpenAI API key."
                    : "Set OPENAI_API_KEY on the backend to enable Vexa."}
                </p>
                <p>Backend: {API_BASE_URL}</p>
              </div>

              <p className="settings-note">
                Also allow Microphone and Accessibility permissions when macOS asks.
              </p>

              {settingsMessage && (
                <p className="settings-message">{settingsMessage}</p>
              )}
            </div>
          )}

          <p className="reply-text">{reply}</p>

          <button
            className="primary-btn"
            disabled={!apiKeyConfigured}
            onClick={() => startListening(true)}
          >
            {isListening ? "Listening..." : "Speak to Vexa"}
          </button>

          <button
            className="secondary-btn"
            onClick={() => setSettingsOpen((open) => !open)}
          >
            Settings
          </button>

          <button className="secondary-btn" onClick={() => loadDashboard(true)}>
            Refresh dashboard
          </button>
        </div>

        <div className="dashboard-panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Live summary</p>
              <h2>Productivity Dashboard</h2>
            </div>
            <span className="window-pill">
              {dashboard?.window?.replaceAll("_", " ") || "today"}
            </span>
          </div>

          <div className="stats-grid">
            <div className="stat-card">
              <span>Productive</span>
              <strong>{dashboard?.totals?.productive ?? 0} min</strong>
            </div>

            <div className="stat-card">
              <span>Neutral</span>
              <strong>{dashboard?.totals?.neutral ?? 0} min</strong>
            </div>

            <div className="stat-card danger">
              <span>Distracting</span>
              <strong>{dashboard?.totals?.distracting ?? 0} min</strong>
            </div>
          </div>

          <div className="comparison-strip">
            <div>
              <span>Yesterday productive</span>
              <strong>{dashboard?.yesterday_totals?.productive ?? 0} min</strong>
            </div>

            <div>
              <span>Today vs yesterday</span>
              <strong>
                {(dashboard?.comparison?.productive_delta ?? 0) >= 0 ? "+" : ""}
                {dashboard?.comparison?.productive_delta ?? 0} min
              </strong>
            </div>
          </div>

          <div className="section-block">
            <h3>Top Apps Today</h3>

            {dashboard?.top_apps_today?.length ? (
              dashboard.top_apps_today.map((app: any) => (
                <div className="app-row" key={app.app_name}>
                  <div>
                    <strong>{app.app_name}</strong>
                    <span>{app.category}</span>
                  </div>
                  <p>{app.minutes} min</p>
                </div>
              ))
            ) : (
              <p className="empty-text">No usage data yet.</p>
            )}
          </div>

          <div className="section-block">
            <h3>Todos</h3>
            <p className="todo-preview">
              {dashboard?.todos || "No todos yet."}
            </p>
          </div>

          <div className="section-block">
            <h3>Ideas</h3>
            <p className="todo-preview">
              {dashboard?.ideas || "No ideas saved yet."}
            </p>
          </div>

          <div className="section-block">
            <h3>Reminders</h3>
            <p className="todo-preview">
              {dashboard?.reminders || "No upcoming reminders."}
            </p>
          </div>
        </div>
      </section>
    </main>
  );
}

function App() {
  return <MainApp />;
}

export default App;

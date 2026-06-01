import { invoke } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import type { PointerEvent } from "react";
import { useEffect, useRef, useState } from "react";
import "./App.css";

function currentWindowLabel() {
  return (window as any).__TAURI_INTERNALS__
    ? getCurrentWindow().label
    : "main";
}

function LauncherApp() {
  const pointerStart = useRef({ x: 0, y: 0 });
  const didDrag = useRef(false);

  async function toggleMainWindow() {
    if (didDrag.current) {
      didDrag.current = false;
      return;
    }

    try {
      await invoke("toggle_main_window");
    } catch (error) {
      console.error(error);
    }
  }

  async function startDrag(event: PointerEvent<HTMLButtonElement>) {
    pointerStart.current = { x: event.clientX, y: event.clientY };
    didDrag.current = false;
  }

  async function dragLauncher(event: PointerEvent<HTMLButtonElement>) {
    const distance =
      Math.abs(event.clientX - pointerStart.current.x) +
      Math.abs(event.clientY - pointerStart.current.y);

    if (distance < 6 || didDrag.current) {
      return;
    }

    didDrag.current = true;

    try {
      await getCurrentWindow().startDragging();
    } catch (error) {
      console.error(error);
    }
  }

  return (
    <main className="launcher-app" data-tauri-drag-region>
      <button
        className="launcher-button"
        type="button"
        aria-label="Open Vexa"
        onClick={toggleMainWindow}
        onPointerDown={startDrag}
        onPointerMove={dragLauncher}
      >
        <span className="launcher-orb">V</span>
      </button>
    </main>
  );
}

function MainApp() {
  const [status, setStatus] = useState("Sleeping...");
  const [reply, setReply] = useState("Say Hey Vexa, or tap the voice button.");
  const [isListening, setIsListening] = useState(false);
  const [dashboard, setDashboard] = useState<any>(null);

  function speak(text: string) {
    const utterance = new SpeechSynthesisUtterance(text);

    const voices = window.speechSynthesis.getVoices();

    const selectedVoice =
      voices.find((v) => v.name.includes("Samantha")) ||
      voices.find((v) => v.name.includes("Victoria")) ||
      voices.find((v) => v.lang.includes("en"));

    if (selectedVoice) {
      utterance.voice = selectedVoice;
    }

    utterance.rate = 1.12;
    utterance.pitch = 1.05;
    utterance.volume = 1;

    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);

    utterance.onend = () => {
      setStatus("Sleeping...");
    };
  }

  async function startListening() {
    try {
      setIsListening(true);
      setStatus("Listening...");
      setReply("Listening... speak now.");

      const res = await fetch("http://127.0.0.1:8000/voice-command", {
        method: "POST",
      });

      const data = await res.json();

      setStatus("Speaking...");
      setReply(data.reply || "Done.");
      speak(data.reply || "Done.");
      loadDashboard();
    } catch (error) {
      console.error(error);
      setStatus("Error");
      setReply("Voice backend is not running.");
    } finally {
      setIsListening(false);
    }
  }

  async function loadDashboard() {
    try {
      const res = await fetch("http://127.0.0.1:8000/dashboard");
      const data = await res.json();
      setDashboard(data);
    } catch (error) {
      console.error(error);
    }
  }

  useEffect(() => {
    loadDashboard();

    const interval = setInterval(() => {
      loadDashboard();
    }, 10000);

    return () => clearInterval(interval);
  }, []);

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

          <div className="status-card">
            <span>Status</span>
            <strong>{status}</strong>
          </div>

          <p className="reply-text">{reply}</p>

          <button className="primary-btn" onClick={startListening}>
            {isListening ? "Listening..." : "Speak to Vexa"}
          </button>

          <button className="secondary-btn" onClick={loadDashboard}>
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
              {dashboard?.window?.replaceAll("_", " ") || "last 20 hours"}
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

          <div className="section-block">
            <h3>Top Apps</h3>

            {dashboard?.top_apps?.length ? (
              dashboard.top_apps.map((app: any) => (
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
        </div>
      </section>
    </main>
  );
}

function App() {
  return currentWindowLabel() === "launcher" ? <LauncherApp /> : <MainApp />;
}

export default App;

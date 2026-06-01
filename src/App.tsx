import { listen } from "@tauri-apps/api/event";
import { useCallback, useEffect, useRef, useState } from "react";
import "./App.css";

function MainApp() {
  const [status, setStatus] = useState("Sleeping...");
  const [reply, setReply] = useState("Say Hey Vexa, or tap the voice button.");
  const [isListening, setIsListening] = useState(false);
  const [dashboard, setDashboard] = useState<any>(null);
  const [dueReminder, setDueReminder] = useState<any>(null);
  const isListeningRef = useRef(false);

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

    utterance.rate = 1.12;
    utterance.pitch = 1.05;
    utterance.volume = 1;

    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);

    utterance.onend = () => {
      setStatus("Sleeping...");
    };
  }, []);

  const loadDashboard = useCallback(async (showStatus = false) => {
    try {
      if (showStatus) {
        setStatus("Refreshing...");
      }

      const res = await fetch("http://127.0.0.1:8000/dashboard");
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

  const checkDueReminders = useCallback(async () => {
    try {
      const res = await fetch("http://127.0.0.1:8000/reminders/due");
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

  const startListening = useCallback(async () => {
    if (isListeningRef.current) {
      return;
    }

    try {
      isListeningRef.current = true;
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
      isListeningRef.current = false;
    }
  }, [loadDashboard, speak]);

  useEffect(() => {
    loadDashboard();
    checkDueReminders();

    const interval = setInterval(() => {
      loadDashboard();
      checkDueReminders();
    }, 10000);

    return () => clearInterval(interval);
  }, [checkDueReminders, loadDashboard]);

  useEffect(() => {
    let unlisten: (() => void) | undefined;

    listen("vexa-start-listening", () => {
      startListening();
    }).then((cleanup) => {
      unlisten = cleanup;
    });

    return () => {
      unlisten?.();
    };
  }, [startListening]);

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

          <p className="reply-text">{reply}</p>

          <button className="primary-btn" onClick={startListening}>
            {isListening ? "Listening..." : "Speak to Vexa"}
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
              {dashboard?.window?.replaceAll("_", " ") || "last 24 hours"}
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

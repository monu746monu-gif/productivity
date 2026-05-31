import { useState } from "react";
import "./App.css";

const API_BASE_URL = "http://127.0.0.1:8000";

type VexaResponse = {
  transcript?: string;
  reply: string;
};

function App() {
  const [status, setStatus] = useState("Sleeping...");
  const [input, setInput] = useState("");
  const [transcript, setTranscript] = useState("");
  const [reply, setReply] = useState("Hi Monu, ask me anything.");
  const [isListening, setIsListening] = useState(false);
  const [usage, setUsage] = useState<any[]>([]);


  function speak(text: string) {
    const utterance = new SpeechSynthesisUtterance(text);

    utterance.rate = 1.15;
    utterance.pitch = 1.12;
    utterance.volume = 1;

    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);

    utterance.onend = () => {
      setStatus("Sleeping...");
    };
  }

  async function askVexa(message?: string) {
    const finalMessage = (message || input).trim();

    if (!finalMessage) return;

    try {
      setStatus("Thinking...");

      const res = await fetch(`${API_BASE_URL}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message: finalMessage,
        }),
      });

      if (!res.ok) {
        throw new Error(`Backend returned ${res.status}`);
      }

      const data = (await res.json()) as VexaResponse;

      if (typeof data.reply !== "string") {
        throw new Error("Backend response must include a reply string.");
      }

      setTranscript(typeof data.transcript === "string" ? data.transcript : finalMessage);
      setReply(data.reply);
      setStatus("Speaking...");
      speak(data.reply);
      setInput("");
    } catch (error) {
      console.error(error);
      setStatus("Error");
      setReply("Backend is not running or returned an invalid response.");
    }
  }async function loadTodayUsage() {
  try {
    setStatus("Loading usage...");

    const res = await fetch("http://127.0.0.1:8000/today-usage");
    const data = await res.json();

    setUsage(data.usage || []);
    setStatus("Sleeping...");
  } catch (error) {
    console.error(error);
    setStatus("Error");
    setReply("Could not load today's usage. Make sure backend is running.");
  }
}
async function startListening() {
  try {
    setIsListening(true);
    setStatus("Listening...");
    setReply("Listening...");

    const res = await fetch(`${API_BASE_URL}/voice-command`, {
      method: "POST",
    });

    if (!res.ok) {
      throw new Error(`Backend returned ${res.status}`);
    }

    const data = (await res.json()) as VexaResponse;

    if (typeof data.transcript !== "string" || typeof data.reply !== "string") {
      throw new Error("Backend response must include transcript and reply strings.");
    }

    setStatus("Speaking...");
    setTranscript(data.transcript);
    setReply(data.reply);

    speak(data.reply);
  } catch (error) {
    console.error(error);
    setStatus("Error");
    setReply("Voice backend is not running or returned an invalid response.");
  } finally {
    setIsListening(false);
  }
}
    

  return (
    <main className="app">
      <div className="assistant-card">
        <div className={isListening ? "orb listening" : "orb"}>V</div>

        <h1>Vexa</h1>

        <p className="subtitle">Your AI productivity companion</p>

        <div className="status-box">
          <p>Status</p>
          <h2>{status}</h2>
        </div>

        {transcript && (
          <p className="transcript">
            You said: <span>{transcript}</span>
          </p>
        )}

        <p className="reply">{reply}</p>

        
<button className="secondary-btn" onClick={loadTodayUsage}>
  Show Today&apos;s Usage
</button>
        <button onClick={() => askVexa()}>Ask Vexa</button>

        <button className="secondary-btn" onClick={startListening}>
          {isListening ? "Listening..." : "Speak to Vexa"}
        </button>
        <div className="usage-box">
  <h3>Today&apos;s Usage</h3>

  {usage.length === 0 ? (
    <p>No usage data yet.</p>
  ) : (
    usage.map((item) => (
      <div className="usage-row" key={item.app_name}>
        <span>{item.app_name}</span>
        <strong>{item.minutes} min</strong>
      </div>
    ))
  )}
</div>

      </div>
    </main>
  );
}

export default App;

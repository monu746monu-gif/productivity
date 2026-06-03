import { listen } from "@tauri-apps/api/event";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiUrl } from "./api";
import assistantAvatar from "./assets/vexa-assistant-avatar.png";
import "./App.css";

const VOICE_RECORD_MS = 10000;

type VoiceCommandResponse = {
  transcript?: string;
  reply?: string;
  missing_api_key?: boolean;
};

function isTauriApp() {
  return "__TAURI_INTERNALS__" in window;
}

function microphoneErrorMessage(error: unknown) {
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError" || error.name === "SecurityError") {
      return isTauriApp()
        ? "Microphone access is blocked. Open System Settings > Privacy & Security > Microphone, allow Vexa, then restart Vexa."
        : "Microphone access is blocked. Allow microphone access in your browser and try again.";
    }

    if (error.name === "NotFoundError") {
      return "No microphone was found. Connect a microphone and try again.";
    }
  }

  return "Microphone recording failed. Allow microphone access for Vexa and restart the app.";
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

  let stream: MediaStream;

  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (error) {
    throw new Error(microphoneErrorMessage(error));
  }

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
  try {
    return await sendBrowserVoiceCommand();
  } catch (error) {
    if (!isTauriApp()) {
      throw error;
    }

    if (error instanceof Error && error.message.includes("Audio recording is not supported")) {
      return sendNativeVoiceCommand();
    }

    throw error;
  }
}

function MainApp() {
  const [status, setStatus] = useState("Sleeping...");
  const [reply, setReply] = useState("Say Hey Vexa, or tap the voice button.");
  const [apiKeyConfigured, setApiKeyConfigured] = useState(false);
  const [isWindowOpening, setIsWindowOpening] = useState(true);
  const isListeningRef = useRef(false);
  const continuousConversationRef = useRef(false);
  const listeningRunIdRef = useRef(0);
  const openAnimationTimeoutRef = useRef<number | null>(null);
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
      await res.json();

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

      if (!configured) {
        const message = "Vexa is not configured with the server API key yet.";
        setReply(message);
      }
    } catch (error) {
      console.error(error);
      setReply("Backend is not running yet.");
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

      setStatus("Reminder");
      setReply(reminderText);
      speak(reminderText);
      loadDashboard();
    } catch (error) {
      console.error(error);
    }
  }, [loadDashboard, speak]);

  const checkFocusAlert = useCallback(async () => {
    if (isListeningRef.current) {
      return;
    }

    try {
      const res = await fetch(apiUrl("/focus-alert"));
      const data = await res.json();

      if (!data.alert || !data.message) {
        return;
      }

      setStatus("Speaking...");
      setReply(data.message);
      speak(data.message);
    } catch (error) {
      console.error(error);
    }
  }, [speak]);

  const startListening = useCallback(async (continuous = true) => {
    if (!apiKeyConfigured) {
      continuousConversationRef.current = false;
      const message = "Vexa is not configured with the server API key yet.";
      setReply(message);
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
      setStatus("Listening...");
      setReply("I'm listening. Take your time.");

      const data = await sendVoiceCommand();

      if (runId !== listeningRunIdRef.current) {
        return;
      }

      const rawTranscript = String(data.transcript || "").trim();
      const transcript = rawTranscript.toLowerCase();
      const shouldStop =
        transcript.includes("stop listening") ||
        transcript.includes("stop conversation") ||
        transcript.includes("go to sleep") ||
        transcript.includes("sleep now");

      if (shouldStop) {
        continuousConversationRef.current = false;
      }

      const vexaReply = shouldStop
        ? "Okay Monu, I will stop listening."
        : data.reply || "Done.";

      setStatus("Speaking...");
      setReply(vexaReply);
      speak(vexaReply);
      loadDashboard();
    } catch (error) {
      console.error(error);
      continuousConversationRef.current = false;
      setStatus("Error");
      const message = error instanceof Error ? error.message : "Vexa voice command failed.";
      setReply(message);
    } finally {
      isListeningRef.current = false;
    }
  }, [apiKeyConfigured, loadDashboard, speak]);

  useEffect(() => {
    startListeningRef.current = startListening;
  }, [startListening]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setIsWindowOpening(false);
    }, 720);

    return () => window.clearTimeout(timeoutId);
  }, []);

  useEffect(() => {
    loadSettings();
    loadDashboard();
    checkDueReminders();
    checkFocusAlert();

    const interval = setInterval(() => {
      loadDashboard();
      checkDueReminders();
      checkFocusAlert();
    }, 20000);

    return () => clearInterval(interval);
  }, [checkDueReminders, checkFocusAlert, loadDashboard, loadSettings]);

  useEffect(() => {
    let unlistenStart: (() => void) | undefined;
    let unlistenStop: (() => void) | undefined;

    const playOpenAnimation = () => {
      if (openAnimationTimeoutRef.current) {
        window.clearTimeout(openAnimationTimeoutRef.current);
      }

      setIsWindowOpening(false);
      window.requestAnimationFrame(() => {
        setIsWindowOpening(true);
        openAnimationTimeoutRef.current = window.setTimeout(() => {
          setIsWindowOpening(false);
          openAnimationTimeoutRef.current = null;
        }, 720);
      });
    };

    listen("vexa-start-listening", () => {
      playOpenAnimation();

      if (!apiKeyConfigured) {
        const message = "Vexa is not configured with the server API key yet.";
        setReply(message);
        return;
      }

      if (isListeningRef.current || continuousConversationRef.current) {
        return;
      }

      const greeting = "Hey Monu, what's going on?";
      continuousConversationRef.current = true;
      setStatus("Speaking...");
      setReply(greeting);
      speak(greeting);
    }).then((cleanup) => {
      unlistenStart = cleanup;
    });

    listen("vexa-stop-listening", () => {
      continuousConversationRef.current = false;
      listeningRunIdRef.current += 1;
      window.speechSynthesis.cancel();
      isListeningRef.current = false;
      setStatus("Sleeping...");
      setReply("Sleeping...");
    }).then((cleanup) => {
      unlistenStop = cleanup;
    });

    return () => {
      unlistenStart?.();
      unlistenStop?.();

      if (openAnimationTimeoutRef.current) {
        window.clearTimeout(openAnimationTimeoutRef.current);
      }
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
    <main className={isWindowOpening ? "app opening" : "app"} aria-label={reply}>
      <section className="shell">
        <div className="assistant-panel">
          <div className={orbClass}>
            <img
              className="orb-avatar"
              src={assistantAvatar}
              alt="Vexa assistant"
            />
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

from flask import Flask, request, jsonify
import threading
import time
import uuid
import os
import requests
import google.generativeai as genai
from datetime import datetime, timedelta
from dotenv import load_dotenv

# === Load .env ===
load_dotenv()
TELEX_WEBHOOK_URL = os.getenv("TELEX_WEBHOOK_URL")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    raise ValueError("❌ GOOGLE_API_KEY not found. Please check your .env file!")

# === Configure Gemini ===
genai.configure(api_key=GOOGLE_API_KEY)

# === Flask app ===
app = Flask(__name__)

# === In-memory storage ===
SESSIONS = {}
USER_SUMMARIES = {}
lock = threading.Lock()

# === Helper function to send to Telex ===
def send_to_telex(channel_id: str, message: str):
    payload = {"channel_id": channel_id, "text": message}
    if not TELEX_WEBHOOK_URL:
        app.logger.info(f"(DEBUG) Would send to Telex: {payload}")
        return
    try:
        requests.post(TELEX_WEBHOOK_URL, json=payload, timeout=5)
    except Exception as e:
        app.logger.error(f"Failed to send message to Telex: {e}")

# === AI helper ===
def ai_generate(message: str):
    """Generate AI message using Gemini."""
    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(message)
        return response.text.strip()
    except Exception as e:
        app.logger.error(f"AI generation failed: {e}")
        return "⚠️ AI failed to respond."

# === Focus session handling ===
def end_focus(session_id):
    with lock:
        session = SESSIONS.get(session_id)
        if not session:
            return
        session["status"] = "focus_completed"
    ai_msg = ai_generate("Generate a short motivational message for completing a focus session.")
    send_to_telex(session["channel_id"], f"⏰ Focus session finished for <@{session['user_id']}>! {ai_msg}\nTime for a {session['break']} minute break.")
    t = threading.Timer(session["break"] * 60, end_break, args=(session_id,))
    t.daemon = True
    t.start()

def end_break(session_id):
    with lock:
        session = SESSIONS.get(session_id)
        if not session:
            return
        session["status"] = "completed"
        session["completed_at"] = datetime.utcnow().isoformat()
    ai_msg = ai_generate("Send a cheerful message to start a new focus session after a break.")
    send_to_telex(session["channel_id"], f"✅ Break over — {ai_msg}")

# === Routes ===

@app.route("/start_focus", methods=["POST"])
def start_focus():
    data = request.get_json() or {}
    user_id = data.get("user_id")
    channel_id = data.get("channel_id")
    duration = int(data.get("duration", 25))
    brk = int(data.get("break", 5))

    if not user_id or not channel_id:
        return jsonify({"error": "user_id and channel_id required"}), 400

    session_id = str(uuid.uuid4())
    start = datetime.now()
    end = start + timedelta(minutes=duration)

    session = {
        "session_id": session_id,
        "user_id": user_id,
        "channel_id": channel_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration": duration,
        "break": brk,
        "status": "running",
    }

    with lock:
        SESSIONS[session_id] = session

    ai_msg = ai_generate(f"Give a motivating start message for a {duration}-minute focus session.")
    send_to_telex(channel_id, f"🚀 <@{user_id}> started a {duration}-minute focus session.\n{ai_msg}")

    t = threading.Timer(duration * 60, end_focus, args=(session_id,))
    t.daemon = True
    t.start()

    return jsonify({"session_id": session_id, "status": "started"})

@app.route("/stop_focus", methods=["POST"])
def stop_focus():
    data = request.get_json() or {}
    session_id = data.get("session_id")
    user_id = data.get("user_id")

    if not session_id and not user_id:
        return jsonify({"error": "session_id or user_id required"}), 400

    with lock:
        if session_id:
            session = SESSIONS.get(session_id)
            if not session:
                return jsonify({"error": "session not found"}), 404
            session["status"] = "stopped"
            ai_msg = ai_generate("Encourage the user kindly after stopping a focus session early.")
            send_to_telex(session["channel_id"], f"🛑 Focus session stopped for <@{session['user_id']}>.\n{ai_msg}")
            return jsonify({"status": "stopped"})
        else:
            for sid, s in list(SESSIONS.items())[::-1]:
                if s["user_id"] == user_id and s["status"] == "running":
                    s["status"] = "stopped"
                    ai_msg = ai_generate("Encourage the user kindly after stopping a focus session early.")
                    send_to_telex(s["channel_id"], f"🛑 Focus session stopped for <@{user_id}>.\n{ai_msg}")
                    return jsonify({"status": "stopped", "session_id": sid})
            return jsonify({"error": "no running session for user"}), 404

@app.route("/status/<user_id>", methods=["GET"])
def status(user_id):
    with lock:
        user_sessions = [s for s in SESSIONS.values() if s["user_id"] == user_id]
    return jsonify({"sessions": user_sessions})

@app.route("/enable_daily_summary", methods=["POST"])
def enable_daily_summary():
    data = request.get_json() or {}
    user_id = data.get("user_id")
    channel_id = data.get("channel_id")
    time_str = data.get("time", "21:00")

    if not user_id or not channel_id:
        return jsonify({"error": "user_id and channel_id required"}), 400

    USER_SUMMARIES[user_id] = {"enabled": True, "time": time_str, "channel_id": channel_id}
    send_to_telex(channel_id, f"🕒 Daily summary enabled for <@{user_id}> at {time_str} UTC.")
    return jsonify({"status": "daily_summary_enabled", "time": time_str})

# === Daily summary background worker ===
def daily_summary_worker():
    sent_today = set()
    while True:
        now = datetime.now()
        hhmm = now.strftime("%H:%M")
        with lock:
            for user_id, cfg in USER_SUMMARIES.items():
                if not cfg.get("enabled"):
                    continue
                if cfg.get("time") == hhmm and (user_id, hhmm) not in sent_today:
                    completed = [s for s in SESSIONS.values() if s["user_id"] == user_id and s.get("status") in ("completed", "focus_completed")]
                    total_sessions = len(completed)
                    total_minutes = sum(s.get("duration", 0) for s in completed)
                    ai_msg = ai_generate(f"Create an encouraging daily summary for someone who completed {total_sessions} sessions totaling {total_minutes} minutes.")
                    send_to_telex(cfg["channel_id"], f"📊 Daily Focus Summary: {ai_msg}")
                    sent_today.add((user_id, hhmm))
            if hhmm == "00:00":
                sent_today.clear()
        time.sleep(30)

# === Start background worker ===
t = threading.Thread(target=daily_summary_worker, daemon=True)
t.start()

@app.route("/webhook", methods=["POST"])
def webhook():
    """Generic webhook for Telex to trigger AI actions."""
    data = request.json or {}
    user_message = data.get("text") or data.get("prompt") or "Hello!"
    ai_reply = ai_generate(user_message)
    return jsonify({"reply": ai_reply, "timestamp": datetime.now()})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)

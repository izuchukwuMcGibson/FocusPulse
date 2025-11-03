"""
FocusPulse - Telex.im Agent (Flask)

Single-file Flask app that implements a simple FocusPulse agent:
- Start focus session: POST /start_focus
- Stop focus session: POST /stop_focus
- Query status: GET /status/<user_id>
- Enable daily summary: POST /enable_daily_summary

Behavior:
- Stores sessions in-memory (dict). Each session schedules a timer that sends messages to Telex when focus completes and when break completes.
- send_to_telex() is a placeholder that POSTS to a TELEX_WEBHOOK_URL (set as env var).

Notes:
- For production, persist sessions to a DB and use a robust scheduler (APScheduler or Celery).
- Set environment variable TELEX_WEBHOOK_URL to your telex incoming webhook or integration endpoint.
- Dependencies: Flask, requests

Example usage:
curl -X POST http://localhost:5000/start_focus -H 'Content-Type: application/json' -d '{"user_id":"u123","channel_id":"c123","duration":45,"break":5}'

"""
from flask import Flask, request, jsonify
import threading
import time
import uuid
import os
import requests
from datetime import datetime, timedelta

app = Flask(__name__)

# In-memory storage (replace with DB in prod)
SESSIONS = {}  # session_id -> {user_id, channel_id, start, end, duration, break, status}
USER_SUMMARIES = {}  # user_id -> {enabled: bool, time: "HH:MM"}

TELEX_WEBHOOK_URL = os.environ.get('TELEX_WEBHOOK_URL')  # set this to your Telex incoming webhook

lock = threading.Lock()


def send_to_telex(channel_id: str, message: str):
    """Sends a message to telex. Replace with actual integration (A2A/Outgoing webhook)."""
    payload = {
        "channel_id": channel_id,
        "text": message,
    }
    if not TELEX_WEBHOOK_URL:
        app.logger.info('TELEX_WEBHOOK_URL not set — would send: %s', payload)
        return True
    try:
        resp = requests.post(TELEX_WEBHOOK_URL, json=payload, timeout=5)
        resp.raise_for_status()
        return True
    except Exception as e:
        app.logger.exception('Failed to send to Telex: %s', e)
        return False


def end_focus(session_id):
    with lock:
        session = SESSIONS.get(session_id)
        if not session:
            return
        session['status'] = 'focus_completed'
    # send message to telex channel
    send_to_telex(session['channel_id'], f"⏰ Focus session finished for <@{session['user_id']}>! Time for a {session['break']} minute break.")

    # schedule break end
    t = threading.Timer(session['break'] * 60, end_break, args=(session_id,))
    t.daemon = True
    t.start()


def end_break(session_id):
    with lock:
        session = SESSIONS.get(session_id)
        if not session:
            return
        session['status'] = 'completed'
        # record completed_at
        session['completed_at'] = datetime.now()
    send_to_telex(session['channel_id'], f"✅ Break over — ready for the next focus session, <@{session['user_id']}>?")


@app.route('/start_focus', methods=['POST'])
def start_focus():
    data = request.get_json() or {}
    user_id = data.get('user_id')
    channel_id = data.get('channel_id')
    duration = int(data.get('duration', 25))  # minutes
    brk = int(data.get('break', 5))  # break minutes

    if not user_id or not channel_id:
        return jsonify({'error': 'user_id and channel_id required'}), 400

    session_id = str(uuid.uuid4())
    start = datetime.now()
    end = start + timedelta(minutes=duration)

    session = {
        'session_id': session_id,
        'user_id': user_id,
        'channel_id': channel_id,
        'start': start.isoformat(),
        'end': end.isoformat(),
        'duration': duration,
        'break': brk,
        'status': 'running'
    }

    with lock:
        SESSIONS[session_id] = session

    # notify channel
    send_to_telex(channel_id, f"🚀 <@{user_id}> started a {duration}-minute focus session. I'll remind you when it's done.")

    # schedule end
    t = threading.Timer(duration * 60, end_focus, args=(session_id,))
    t.daemon = True
    t.start()

    return jsonify({'session_id': session_id, 'status': 'started'})


@app.route('/stop_focus', methods=['POST'])
def stop_focus():
    data = request.get_json() or {}
    session_id = data.get('session_id')
    user_id = data.get('user_id')

    if not session_id and not user_id:
        return jsonify({'error': 'session_id or user_id required'}), 400

    with lock:
        if session_id:
            session = SESSIONS.get(session_id)
            if not session:
                return jsonify({'error': 'session not found'}), 404
            session['status'] = 'stopped'
            send_to_telex(session['channel_id'], f"🛑 Focus session stopped for <@{session['user_id']}>.")
            return jsonify({'status': 'stopped'})
        else:
            # stop the latest running session for user
            for sid, s in list(SESSIONS.items())[::-1]:
                if s['user_id'] == user_id and s['status'] == 'running':
                    s['status'] = 'stopped'
                    send_to_telex(s['channel_id'], f"🛑 Focus session stopped for <@{user_id}>.")
                    return jsonify({'status': 'stopped', 'session_id': sid})
            return jsonify({'error': 'no running session for user'}), 404


@app.route('/status/<user_id>', methods=['GET'])
def status(user_id):
    with lock:
        user_sessions = [s for s in SESSIONS.values() if s['user_id'] == user_id]
    return jsonify({'sessions': user_sessions})


@app.route('/enable_daily_summary', methods=['POST'])
def enable_daily_summary():
    data = request.get_json() or {}
    user_id = data.get('user_id')
    channel_id = data.get('channel_id')
    time_str = data.get('time', '21:00')  # HH:MM in user local time (simple)

    if not user_id or not channel_id:
        return jsonify({'error': 'user_id and channel_id required'}), 400

    USER_SUMMARIES[user_id] = {'enabled': True, 'time': time_str, 'channel_id': channel_id}
    return jsonify({'status': 'daily_summary_enabled', 'time': time_str})


def daily_summary_worker():
    """Background thread that checks once a minute and sends daily summaries when due."""
    sent_today = set()
    while True:
        now = datetime.now()
        hhmm = now.strftime('%H:%M')
        with lock:
            for user_id, cfg in USER_SUMMARIES.items():
                if not cfg.get('enabled'):
                    continue
                # NOTE: This simple implementation expects time in UTC HH:MM to avoid timezone handling complexity.
                if cfg.get('time') == hhmm and (user_id, hhmm) not in sent_today:
                    # compute today's completed focus sessions
                    with lock:
                        completed = [s for s in SESSIONS.values() if s['user_id'] == user_id and s.get('status') in ('completed', 'focus_completed')]
                    total_sessions = len(completed)
                    total_minutes = sum(s.get('duration', 0) for s in completed)
                    msg = f"📊 Daily Focus Summary: You completed {total_sessions} sessions today, totaling {total_minutes} minutes. Keep it up!"
                    send_to_telex(cfg['channel_id'], msg)
                    sent_today.add((user_id, hhmm))
            # reset sent_today at midnight UTC
            if hhmm == '00:00':
                sent_today.clear()
        time.sleep(30)


if __name__ == '__main__':
    # start background worker
    t = threading.Thread(target=daily_summary_worker, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', )))

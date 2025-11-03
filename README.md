# FocusPulse Agent for Telex.im

## Overview
**FocusPulse Agent** is a simple and smart Telex.im integration that helps users manage their focus sessions and stay productive.  
It allows users to start/stop focus sessions, track active time, and receive daily summaries â€” all through Telex.im interactions.

---

## Features
- Start and stop focus sessions easily
- Check current focus status
-  Receive automatic daily productivity summaries
- Uses scheduled tasks for automated updates
-  Seamlessly integrates into Telex.im via workflow.json

---

## Project Structure
```
focuspulse-agent/
â”‚
 app.py                 # Flask backend with endpoints
 workflow.json          # Telex.im workflow integration file
requirements.txt       # Dependencies
README.md              # Project documentation
```

---

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/focuspulse-agent.git
   cd focuspulse-agent
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set your environment variables:**
   ```bash
   export TELEX_WEBHOOK_URL="https://your-telex-webhook-url.com"
   ```

4. **Run the app:**
   ```bash
   python app.py
   ```

---

## Deployment
You can deploy this app on:
- **Render**
- **Railway**
- **Vercel (via Serverless functions)**
- **Any Flask-compatible hosting**

Make sure your appâ€™s base URL is accessible to Telex.im.

---

## API Endpoints

| Endpoint | Method | Description |
|-----------|--------|-------------|
| `/start_focus` | POST | Start a focus session |
| `/stop_focus` | POST | End the current focus session |
| `/status/<user_id>` | GET | Get user focus session details |
| `/enable_daily_summary` | POST | Turn on daily summaries for a user |

---

## Workflow Integration (Telex.im)

This project includes a ready-made `workflow.json` file that defines:
- Triggers for commands
- Action routes to Flask endpoints
- Scheduling for daily summaries

To integrate:
1. Go to your **Telex.im dashboard**.
2. Import the `workflow.json` file.
3. Connect it with your running Flask app.

---

## Example Usage
**User on Telex.im:**
> `/focus start`  
> `/focus stop`  
> `/focus status`

**Agent Response:**
> Focus session started. Stay productive!

---

## License
MIT License © 2025 FocusPulse Team

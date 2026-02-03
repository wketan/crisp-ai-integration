"""
Crisp AI Integration - Powered by Claude
"""
import os
import json
import time
import requests
import schedule
from datetime import datetime
from dotenv import load_dotenv
import anthropic

load_dotenv()

CRISP_IDENTIFIER = os.getenv('CRISP_IDENTIFIER')
CRISP_KEY = os.getenv('CRISP_KEY')
CRISP_WEBSITE_ID = os.getenv('CRISP_WEBSITE_ID')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL')

CRISP_API_BASE = "https://api.crisp.chat/v1"
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

def get_crisp_headers():
      import base64
      auth = f"{CRISP_IDENTIFIER}:{CRISP_KEY}"
      return {"Authorization": f"Basic {base64.b64encode(auth.encode()).decode()}", "X-Crisp-Tier": "plugin", "Content-Type": "application/json"}

def get_conversations():
      r = requests.get(f"{CRISP_API_BASE}/website/{CRISP_WEBSITE_ID}/conversations/list", headers=get_crisp_headers())
      return r.json().get("data", []) if r.status_code == 200 else []

def get_messages(session_id):
      r = requests.get(f"{CRISP_API_BASE}/website/{CRISP_WEBSITE_ID}/conversation/{session_id}/messages", headers=get_crisp_headers())
      return r.json().get("data", []) if r.status_code == 200 else []

def add_note(session_id, content):
      r = requests.post(f"{CRISP_API_BASE}/website/{CRISP_WEBSITE_ID}/conversation/{session_id}/message", headers=get_crisp_headers(), json={"type": "note", "from": "operator", "origin": "chat", "content": content})
      return r.status_code in [200, 201]

def analyze_chat(messages):
      text = "\n".join([f"[{'Customer' if m.get('from')=='user' else 'Agent'}]: {m.get('content','')}" for m in messages[-50:] if m.get('content')])
      try:
                r = claude.messages.create(model="claude-sonnet-4-20250514", max_tokens=1024, messages=[{"role": "user", "content": f"Summarize this support chat:\n{text}"}])
                return r.content[0].text
            except: return None

  def send_slack(msg):
        requests.post(SLACK_WEBHOOK_URL, json={"blocks": [{"type": "header", "text": {"type": "plain_text", "text": f"Crisp Summary - {datetime.now().strftime('%I:%M %p')}", "emoji": True}}, {"type": "section", "text": {"type": "mrkdwn", "text": msg}}]})

def hourly_summary():
      convs = get_conversations()
      if not convs: send_slack("No active chats"); return
            summaries = []
    for c in convs[:10]:
              msgs = get_messages(c.get("session_id"))
              if msgs:
                            s = analyze_chat(msgs)
                            if s: summaries.append(s)
                                  if summaries: send_slack("\n\n".join(summaries))

                def main():
                      print("Starting Crisp AI Integration")
                      schedule.every().hour.at(":00").do(hourly_summary)
                      hourly_summary()
                      while True:
                                schedule.run_pending()
                                time.sleep(30)

                  if __name__ == "__main__":
                        main()

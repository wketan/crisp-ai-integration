"""
Crisp AI Integration - Powered by Claude
- Hourly Slack summaries (IST timezone) with detailed analysis
- Crisp sidebar widget for on-demand chat summaries
"""
import os
import json
import time
import base64
import threading
import requests
import schedule
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify
import anthropic

# IST Timezone (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

# Environment variables
CRISP_IDENTIFIER = os.getenv('CRISP_IDENTIFIER')
CRISP_KEY = os.getenv('CRISP_KEY')
CRISP_WEBSITE_ID = os.getenv('CRISP_WEBSITE_ID')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL')

CRISP_API_BASE = "https://api.crisp.chat/v1"
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
app = Flask(__name__)

def get_ist_time():
    return datetime.now(IST)

def get_crisp_headers():
    auth = f"{CRISP_IDENTIFIER}:{CRISP_KEY}"
    encoded = base64.b64encode(auth.encode()).decode()
    return {
        "Authorization": f"Basic {encoded}",
        "X-Crisp-Tier": "plugin",
        "Content-Type": "application/json"
    }

def get_conversations(page=1):
    """Get list of conversations from Crisp"""
    try:
        url = f"{CRISP_API_BASE}/website/{CRISP_WEBSITE_ID}/conversations/{page}"
        print(f"Fetching conversations from: {url}")
        r = requests.get(url, headers=get_crisp_headers())
        print(f"Response status: {r.status_code}")
        if r.status_code == 200:
            data = r.json().get("data", [])
            print(f"Found {len(data)} conversations")
            return data
        else:
            print(f"Error response: {r.text}")
            return []
    except Exception as e:
        print(f"Error fetching conversations: {e}")
        return []

def get_messages(session_id):
    """Get messages from a specific conversation"""
    try:
        url = f"{CRISP_API_BASE}/website/{CRISP_WEBSITE_ID}/conversation/{session_id}/messages"
        r = requests.get(url, headers=get_crisp_headers())
        if r.status_code == 200:
            return r.json().get("data", [])
        return []
    except Exception as e:
        print(f"Error fetching messages: {e}")
        return []

def add_note(session_id, content):
    """Add an internal note to a conversation"""
    try:
        url = f"{CRISP_API_BASE}/website/{CRISP_WEBSITE_ID}/conversation/{session_id}/message"
        payload = {
            "type": "note",
            "from": "operator",
            "origin": "chat",
            "content": content
        }
        r = requests.post(url, headers=get_crisp_headers(), json=payload)
        print(f"Add note response: {r.status_code}")
        return r.status_code in [200, 201]
    except Exception as e:
        print(f"Error adding note: {e}")
        return False

def analyze_chat_detailed(messages):
    """Detailed analysis: issue, sentiment, urgency, steps taken"""
    if not messages:
        return None

    formatted = []
    for m in messages[-50:]:
        if m.get('content'):
            sender = 'Customer' if m.get('from') == 'user' else 'Support'
            formatted.append(f"[{sender}]: {m.get('content', '')}")

    if not formatted:
        return None

    text = "\n".join(formatted)

    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": f"""Analyze this support chat and provide a structured analysis:

1. **Issue**: What is the main problem/question the customer has?
2. **Sentiment**: Customer mood (Positive/Neutral/Frustrated/Angry)
3. **Urgency**: Level of urgency (Low/Medium/High/Critical)
4. **Steps Taken**: What actions has support taken so far?
5. **Status**: Current status (Resolved/In Progress/Pending/Escalated)

Keep each section brief (1-2 sentences max).

Chat transcript:
{text}"""
            }]
        )
        return response.content[0].text
    except Exception as e:
        print(f"Error analyzing chat: {e}")
        return None

def analyze_for_widget(messages):
    """Quick analysis for sidebar widget: issue and steps taken"""
    if not messages:
        return None

    formatted = []
    for m in messages[-30:]:
        if m.get('content'):
            sender = 'Customer' if m.get('from') == 'user' else 'Support'
            formatted.append(f"[{sender}]: {m.get('content', '')}")

    if not formatted:
        return None

    text = "\n".join(formatted)

    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": f"""Analyze this chat and provide:

**Issue**: What is the customer's problem? (1-2 sentences)

**Steps Taken by Support**: What has the support agent done? (bullet points)

**Recommendation**: What should be done next? (1 sentence)

Chat:
{text}"""
            }]
        )
        return response.content[0].text
    except Exception as e:
        print(f"Error analyzing chat: {e}")
        return None

def send_slack(msg):
    """Send a message to Slack"""
    if not SLACK_WEBHOOK_URL or not msg:
        print("No Slack webhook URL or empty message")
        return

    ist_time = get_ist_time()

    try:
        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"Crisp Summary - {ist_time.strftime('%I:%M %p IST')}",
                        "emoji": True
                    }
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": msg
                    }
                },
                {"type": "divider"},
                {
                    "type": "context",
                    "elements": [{
                        "type": "mrkdwn",
                        "text": f"Generated by Crisp AI | {ist_time.strftime('%Y-%m-%d %H:%M IST')}"
                    }]
                }
            ]
        }
        r = requests.post(SLACK_WEBHOOK_URL, json=payload)
        print(f"Slack response: {r.status_code}")
    except Exception as e:
        print(f"Error sending to Slack: {e}")

def hourly_summary():
    """Generate hourly summary of latest 15 chats with detailed analysis"""
    ist_time = get_ist_time()
    print(f"\n=== Running hourly summary at {ist_time.strftime('%Y-%m-%d %H:%M IST')} ===")

    convs = get_conversations()

    if not convs:
        send_slack("*No active chats in Crisp at this time.*")
        return

    summaries = []
    for conv in convs[:15]:  # Latest 15 chats
        session_id = conv.get("session_id")
        if not session_id:
            continue

        msgs = get_messages(session_id)
        if msgs:
            analysis = analyze_chat_detailed(msgs)
            if analysis:
                nickname = conv.get('meta', {}).get('nickname', 'Unknown Customer')
                summaries.append(f"*{nickname}*\n{analysis}")

        time.sleep(0.5)

    if summaries:
        header = f"*Hourly Chat Analysis - {ist_time.strftime('%I:%M %p IST')}*\n*Total Chats Analyzed: {len(summaries)}*\n\n"
        full_summary = header + "\n\n---\n\n".join(summaries)
        send_slack(full_summary)
    else:
        send_slack("*No chat activity to summarize.*")

# Crisp Widget endpoint - called when sidebar button is clicked
@app.route('/widget', methods=['POST', 'GET'])
def widget():
    """Handle Crisp sidebar widget requests"""
    try:
        if request.method == 'GET':
            # Initial widget load - return HTML interface
            return '''
            <html>
            <head>
                <style>
                    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; padding: 15px; background: #f5f5f5; }
                    .btn { background: #4A90D9; color: white; border: none; padding: 12px 20px; border-radius: 6px; cursor: pointer; width: 100%; font-size: 14px; }
                    .btn:hover { background: #3A7BC8; }
                    #result { margin-top: 15px; padding: 15px; background: white; border-radius: 6px; white-space: pre-wrap; font-size: 13px; line-height: 1.5; }
                    .loading { color: #666; }
                </style>
            </head>
            <body>
                <button class="btn" onclick="summarize()">Summarize This Chat</button>
                <div id="result"></div>
                <script>
                    function summarize() {
                        document.getElementById('result').innerHTML = '<span class="loading">Analyzing chat...</span>';
                        const sessionId = window.parent.Crisp?.chat?.session_id || new URLSearchParams(window.location.search).get('session_id');
                        fetch('/widget/analyze?session_id=' + sessionId)
                            .then(r => r.json())
                            .then(data => {
                                document.getElementById('result').innerHTML = data.summary || data.error || 'No summary available';
                            })
                            .catch(e => {
                                document.getElementById('result').innerHTML = 'Error: ' + e.message;
                            });
                    }
                </script>
            </body>
            </html>
            '''

        # POST request from Crisp webhook
        data = request.json
        session_id = data.get('data', {}).get('session_id') or data.get('session_id')

        if session_id:
            msgs = get_messages(session_id)
            if msgs:
                analysis = analyze_for_widget(msgs)
                if analysis:
                    return jsonify({"status": "success", "summary": analysis})

        return jsonify({"status": "error", "message": "Could not analyze chat"})

    except Exception as e:
        print(f"Widget error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/widget/analyze', methods=['GET'])
def widget_analyze():
    """Analyze a specific chat session for the widget"""
    try:
        session_id = request.args.get('session_id')
        if not session_id:
            return jsonify({"error": "No session ID provided"})

        msgs = get_messages(session_id)
        if msgs:
            analysis = analyze_for_widget(msgs)
            if analysis:
                # Also add as internal note
                add_note(session_id, f"**AI Analysis:**\n\n{analysis}")
                return jsonify({"summary": analysis})

        return jsonify({"error": "No messages found"})

    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhooks from Crisp"""
    try:
        data = request.json
        print(f"Received webhook: {json.dumps(data, indent=2)}")
        return jsonify({"status": "ok"})
    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({"status": "error"}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    ist_time = get_ist_time()
    return jsonify({
        "status": "healthy",
        "timestamp_ist": ist_time.isoformat(),
        "crisp_website_id": CRISP_WEBSITE_ID[:8] + "..." if CRISP_WEBSITE_ID else None
    })

@app.route('/test-summary', methods=['GET'])
def test_summary():
    """Manually trigger a summary for testing"""
    hourly_summary()
    return jsonify({"status": "summary triggered"})

def run_scheduler():
    """Run the scheduler in a background thread"""
    schedule.every().hour.at(":00").do(hourly_summary)
    print("Scheduler started - hourly summaries at :00")

    while True:
        schedule.run_pending()
        time.sleep(30)

def main():
    ist_time = get_ist_time()
    print("=" * 50)
    print("Starting Crisp AI Integration")
    print(f"Website ID: {CRISP_WEBSITE_ID}")
    print(f"Current IST Time: {ist_time.strftime('%Y-%m-%d %H:%M IST')}")
    print("=" * 50)

    print("\nRunning initial summary...")
    hourly_summary()

    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    port = int(os.getenv('PORT', 8080))
    print(f"\nStarting webhook server on port {port}")
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    main()

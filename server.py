import os
import time
import requests
from flask import Flask, request, Response

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
LANG = os.environ.get("SPEECH_LANG", "he-IL")

SYSTEM_PROMPT = (
    "אתה עוזר קולי בטלפון. עונה בעברית בשפה מכובדת ונקייה, בקצרה "
    "(עד שלושה משפטים), בלי רשימות, בלי כוכביות ובלי עיצוב, כי התשובה "
    "מוקראת בקול. אם המתקשר מדבר בשפה אחרת, ענה בשפתו."
)

app = Flask(__name__)

calls = {}
MAX_TURNS = 20
CALL_TTL = 60 * 60


def cleanup():
    now = time.time()
    for cid in [c for c, v in calls.items() if now - v["last"] > CALL_TTL]:
        calls.pop(cid, None)


def ask_gemini(history):
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{MODEL}:generateContent"
    )
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": history,
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 300},
    }
    r = requests.post(
        url,
        headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
        json=body,
        timeout=25,
    )
    r.raise_for_status()
    data = r.json()
    parts = data["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts).strip()


def clean_for_yemot(text):
    for ch in ["=", ",", "&", "\n", "\r", "*", "#", '"', "'"]:
        text = text.replace(ch, " ")
    return " ".join(text.split())


def say_and_listen(text):
    return f"read=t-{clean_for_yemot(text)}=speech,no,voice,{LANG}"


def say_and_hangup(text):
    return f"id_list_message=t-{clean_for_yemot(text)}&go_to_folder=hangup"


@app.route("/yemot", methods=["GET", "POST"])
def yemot():
    cleanup()
    args = request.values
    call_id = args.get("ApiCallId", "unknown")
    hangup = args.get("ApiHangup", "")
    heard = (args.get("speech") or "").strip()

    if hangup == "yes":
        calls.pop(call_id, None)
        return Response("", mimetype="text/plain")

    state = calls.setdefault(call_id, {"history": [], "last": time.time()})
    state["last"] = time.time()

    if not heard:
        if not state["history"]:
            return Response(
                say_and_listen("שלום, אני מקשיב. במה אפשר לעזור?"),
                mimetype="text/plain; charset=utf-8",
            )
        return Response(
            say_and_listen("לא שמעתי, אפשר לחזור על זה?"),
            mimetype="text/plain; charset=utf-8",
        )

    if heard.replace(".", "").strip() in ("להתראות", "שלום ולהתראות", "ביי", "תודה להתראות"):
        calls.pop(call_id, None)
        return Response(say_and_hangup("להתראות"), mimetype="text/plain; charset=utf-8")

    state["history"].append({"role": "user", "parts": [{"text": heard}]})
    state["history"] = state["history"][-MAX_TURNS * 2:]

    try:
        answer = ask_gemini(state["history"])
        if not answer:
            answer = "לא הצלחתי לענות. אפשר לנסות שוב?"
    except Exception as e:
        print("Gemini error:", e)
        state["history"].pop()
        answer = "יש תקלה זמנית. אפשר לנסות שוב?"

    state["history"].append({"role": "model", "parts": [{"text": answer}]})
    return Response(say_and_listen(answer), mimetype="text/plain; charset=utf-8")


@app.route("/")
def health():
    return "OK"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

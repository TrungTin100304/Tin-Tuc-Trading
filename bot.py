#!/usr/bin/env python3
"""Bot Telegram: tin kinh tế (CPI, Fed, lãi suất...) + lịch bảo trì FTMO.

Nguồn dữ liệu:
  - Lịch kinh tế: feed JSON miễn phí của Forex Factory (nfs.faireconomy.media)
  - Bảo trì FTMO: trang https://ftmo.com/en/trading-updates/ (bài "Trading Update" hàng tuần)
Giờ hiển thị: Asia/Ho_Chi_Minh (đổi bằng biến BOT_TZ).
"""
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
try:
    from curl_cffi import requests as cffi  # giả lập trình duyệt, tránh bị chặn
except ImportError:
    cffi = None


def _direct_get(url, **kw):
    if cffi:
        return cffi.get(url, impersonate="chrome", timeout=20, **kw)
    return requests.get(url, headers=UA, timeout=20, **kw)


def web_get(url, **kw):
    """Tải trang; nếu mạng chặn kết nối thẳng tới ftmo.com thì đọc qua r.jina.ai."""
    try:
        return _direct_get(url, **kw)
    except Exception as e:
        if "ftmo.com" not in url:
            raise
        print("Kết nối thẳng FTMO lỗi, thử qua r.jina.ai:", e, file=sys.stderr)
        return _direct_get("https://r.jina.ai/" + url, **kw)

# Tự đọc file .env cạnh bot.py
_env = Path(__file__).with_name(".env")
if _env.exists():
    for _l in _env.read_text(encoding="utf-8").splitlines():
        _l = _l.split("#", 1)[0].strip()
        if "=" in _l:
            _k, _v = _l.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TZ = ZoneInfo(os.environ.get("BOT_TZ", "Asia/Ho_Chi_Minh"))
DIGEST_HOUR = int(os.environ.get("DIGEST_HOUR", "7"))        # bản tin sáng
DIGEST_MIN = int(os.environ.get("DIGEST_MIN", "30"))
ALERT_BEFORE_MIN = int(os.environ.get("ALERT_BEFORE_MIN", "30"))  # cảnh báo trước tin
CURRENCIES = {c.strip() for c in os.environ.get("CURRENCIES", "USD").split(",")}
MIN_IMPACT = os.environ.get("MIN_IMPACT", "High")             # High | Medium
STATE_FILE = Path(os.environ.get("STATE_FILE", "state.json"))
# Tin vĩ mô hay làm crypto biến động mạnh: lấy cả tin mức Medium nếu tên khớp từ khóa (USD)
CRYPTO_MODE = os.environ.get("CRYPTO_MODE", "1") == "1"
CRYPTO_KEYWORDS = tuple(k.strip().lower() for k in os.environ.get(
    "CRYPTO_KEYWORDS",
    "CPI,PPI,PCE,FOMC,Federal Funds,Fed Chair,Powell,Non-Farm,Unemployment Rate,"
    "Average Hourly,JOLTS,ISM,Retail Sales,GDP,Treasury,Fed ,Employment Change").split(",") if k.strip())

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FTMO_LIST = "https://ftmo.com/en/trading-updates/"
FTMO_POST_RE = re.compile(r"https://ftmo\.com/(?:[a-z]{2}/)?blog/trading-updates/trading-update-[a-z0-9-]+/")
UA = {"User-Agent": "Mozilla/5.0 (tg-news-bot)"}

# Từ khóa để gắn nhãn tin quan trọng
KEY_WORDS = ("CPI", "FOMC", "Federal Funds", "Interest Rate", "Fed Chair", "Powell",
             "Non-Farm", "NFP", "PCE", "PPI", "Unemployment", "Retail Sales", "GDP")

_ff_cache = {"t": 0.0, "data": []}


# ---------------------------------------------------------------- Telegram
def tg(method, **params):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}", json=params, timeout=40)
    r.raise_for_status()
    return r.json()


def send(text, chat_id=None):
    for i in range(0, len(text), 4000):
        tg("sendMessage", chat_id=chat_id or CHAT_ID, text=text[i:i + 4000],
           parse_mode="HTML", disable_web_page_preview=True)


# ---------------------------------------------------------------- State
def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"ftmo_seen": [], "alerted": [], "digest_day": "", "offset": 0}


def save_state(st):
    st["alerted"] = st["alerted"][-300:]
    st["ftmo_seen"] = st["ftmo_seen"][-30:]
    STATE_FILE.write_text(json.dumps(st))


# ---------------------------------------------------------------- Kinh tế
def fetch_events(force=False):
    """Trả về list sự kiện đã lọc: {title,country,impact,dt(aware),forecast,previous}."""
    if not force and time.time() - _ff_cache["t"] < 1800 and _ff_cache["data"]:
        return _ff_cache["data"]
    try:
        raw = web_get(FF_URL).json()
    except Exception as e:
        print("FF lỗi:", e, file=sys.stderr)
        return _ff_cache["data"]  # dùng cache cũ nếu có
    _ff_cache["data"] = parse_events(raw)
    _ff_cache["t"] = time.time()
    return _ff_cache["data"]


def parse_events(raw):
    order = {"Low": 0, "Medium": 1, "High": 2}
    out = []
    for e in raw:
        if e.get("country") not in CURRENCIES:
            continue
        lvl = order.get(e.get("impact"), -1)
        crypto_hit = (CRYPTO_MODE and e.get("country") == "USD" and lvl >= 1
                      and any(k in e.get("title", "").lower() for k in CRYPTO_KEYWORDS))
        if lvl < order.get(MIN_IMPACT, 2) and not crypto_hit:
            continue
        try:
            dt = datetime.fromisoformat(e["date"]).astimezone(TZ)
        except Exception:
            continue
        out.append({"title": e.get("title", ""), "country": e["country"], "impact": e["impact"],
                    "dt": dt, "forecast": e.get("forecast") or "-", "previous": e.get("previous") or "-"})
    return sorted(out, key=lambda x: x["dt"])


def fmt_event(e, with_day=False):
    star = "🔴" if e["impact"] == "High" else "🟠"
    day = e["dt"].strftime("%a %d/%m ") if with_day else ""
    hot = " ⭐" if any(k.lower() in e["title"].lower() for k in KEY_WORDS) else ""
    return (f"{star} <b>{day}{e['dt']:%H:%M}</b> {e['country']} – {html.escape(e['title'])}{hot}\n"
            f"      DB: {html.escape(e['forecast'])} | Trước: {html.escape(e['previous'])}")


def day_digest(day=None):
    day = day or datetime.now(TZ).date()
    evs = [e for e in fetch_events() if e["dt"].date() == day]
    head = f"📅 <b>Tin kinh tế {day:%d/%m/%Y}</b> (giờ VN)\n"
    if not evs:
        return head + "Không có tin mạnh nào hôm nay."
    return head + "\n".join(fmt_event(e) for e in evs)


def week_digest():
    now = datetime.now(TZ)
    evs = [e for e in fetch_events() if e["dt"] >= now - timedelta(hours=1)]
    if not evs:
        return "📅 Không còn tin mạnh nào trong tuần này."
    return "📅 <b>Tin mạnh còn lại trong tuần</b> (giờ VN)\n" + "\n".join(fmt_event(e, True) for e in evs)


# ---------------------------------------------------------------- FTMO
DATE_RE = re.compile(r"(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\s*,?\s*(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})")
TIME_RE = re.compile(r"(\d{1,2}:\d{2})\s*(?:and|to|[-–—])?\s*(\d{1,2}:\d{2})")
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def html_to_text(h):
    h = re.sub(r"(?is)<(script|style).*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</(p|li|h\d|div|tr)>", "\n", h)
    h = re.sub(r"<[^>]+>", " ", h)
    h = html.unescape(h)
    h = re.sub(r"[*#_`]+", "", h)
    h = re.sub(r"\s+([,.;:])", r"\1", h)  # "Saturday , 21" -> "Saturday, 21"  # bỏ ký hiệu markdown (khi đọc qua r.jina.ai)
    return re.sub(r"[ \t\r\f\v]+", " ", h)


def parse_ftmo_maintenance(text):
    """Trả về (offset_giờ_MT, [(start_dt, end_dt)], đoạn_gốc) với dt theo giờ VN."""
    m = re.search(r"GMT\s*([+-]\s*\d{1,2})", text)
    mt_off = int(m.group(1).replace(" ", "")) if m else 3
    s = re.search(r"Weekend Maintenance", text, re.I)
    if not s:
        return mt_off, [], ""
    e = re.search(r"IT Maintenance|Trading hours|Holiday|Market conditions", text[s.end():], re.I)
    sec = text[s.start(): s.end() + (e.start() if e else 1500)]
    flat = re.sub(r"\s+", " ", sec)
    mt_tz = timezone(timedelta(hours=mt_off))
    windows, cur = [], None
    # duyệt tuần tự: ngày -> các khung giờ đi theo sau
    for tok in re.finditer(DATE_RE.pattern + "|" + TIME_RE.pattern, flat):
        if tok.group(1) and tok.group(2) and tok.group(3) and tok.group(4) is None:
            mo = MONTHS.get(tok.group(2).lower()[:3])
            if mo:
                cur = datetime(int(tok.group(3)), mo, int(tok.group(1))).date()
        elif cur and tok.group(4):
            a, b = tok.group(4), tok.group(5)
            h1, m1 = map(int, a.split(":"))
            h2, m2 = map(int, b.split(":"))
            st = datetime(cur.year, cur.month, cur.day, h1, m1, tzinfo=mt_tz)
            en = datetime(cur.year, cur.month, cur.day, h2 % 24, m2, tzinfo=mt_tz)
            if (h2, m2) == (24, 0) or en <= st:
                en += timedelta(days=1)
            windows.append((st.astimezone(TZ), en.astimezone(TZ)))
    return mt_off, windows, flat


def fetch_latest_ftmo():
    """Trang danh sách chính là bài Trading Update mới nhất. Trả về (text, url_bài)."""
    text = html_to_text(web_get(FTMO_LIST).text)
    m = re.search(r"Trading Update\s*\|\s*(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})", text)
    if not m:
        return text, FTMO_LIST
    slug = f"trading-update-{int(m.group(1))}-{m.group(2).lower()}-{m.group(3)}"
    return text, f"https://ftmo.com/en/blog/trading-updates/{slug}/"


def ftmo_message(text, url):
    off, wins, raw = parse_ftmo_maintenance(text)
    lines = ["🛠 <b>FTMO – Lịch bảo trì cuối tuần</b>"]
    if wins:
        for st, en in wins:
            end = f"{en:%H:%M}" if en.date() == st.date() else f"{en:%a %d/%m %H:%M}"
            lines.append(f"• {st:%a %d/%m %H:%M} → {end} (giờ VN)")
        lines.append(f"<i>Đã quy đổi từ giờ MT (GMT{off:+d}). Trong thời gian này giao dịch bị tắt.</i>")
    elif raw:
        lines.append(html.escape(raw[:700]))
        lines.append("<i>(Không đọc tự động được khung giờ, đây là nguyên văn – giờ MT.)</i>")
    else:
        lines.append("Bài này không thấy mục Weekend Maintenance.")
    lines.append(f'<a href="{url}">Xem bài gốc</a>')
    return "\n".join(lines)


def check_ftmo(st, force=False, chat_id=None):
    text, url = fetch_latest_ftmo()
    if force or url not in st["ftmo_seen"]:
        msg = ftmo_message(text, url)
        if force:
            return msg
        send(msg)
        st["ftmo_seen"].append(url)
    return None


# ---------------------------------------------------------------- Lịch chạy
def tick(st):
    now = datetime.now(TZ)
    # 1) Bản tin sáng
    today = now.strftime("%Y-%m-%d")
    if st["digest_day"] != today and (now.hour, now.minute) >= (DIGEST_HOUR, DIGEST_MIN):
        send(day_digest())
        st["digest_day"] = today
    # 2) Cảnh báo trước tin
    for e in fetch_events():
        left = (e["dt"] - now).total_seconds() / 60
        eid = f"{e['dt']:%Y%m%d%H%M}-{e['title']}"
        if 0 < left <= ALERT_BEFORE_MIN and eid not in st["alerted"]:
            send(f"⏰ <b>Còn ~{int(left)} phút</b> có tin:\n{fmt_event(e)}")
            st["alerted"].append(eid)
    # 3) FTMO (mỗi lần tick, nhưng chỉ tải trang mỗi 30 phút)
    if time.time() - st.get("_ftmo_t", 0) > 1800:
        st["_ftmo_t"] = time.time()
        try:
            check_ftmo(st)
        except Exception as ex:
            print("FTMO lỗi:", ex, file=sys.stderr)


HELP = ("Lệnh:\n/today – tin hôm nay\n/week – tin còn lại trong tuần\n"
        "/ftmo – lịch bảo trì FTMO mới nhất\n/help – trợ giúp")


def handle(msg, st):
    text = (msg.get("text") or "").split("@")[0].strip().lower()
    cid = msg["chat"]["id"]
    try:
        if text in ("/start", "/help"):
            send(f"Chat ID của bạn: <code>{cid}</code>\n{HELP}", cid)
        elif text == "/today":
            send(day_digest(), cid)
        elif text == "/week":
            send(week_digest(), cid)
        elif text == "/ftmo":
            send(check_ftmo(st, force=True), cid)
    except Exception as ex:
        send(f"Lỗi: {html.escape(str(ex))}", cid)


def main():
    if not TOKEN or not CHAT_ID:
        sys.exit("Thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID (xem .env.example)")
    st = load_state()
    print("Bot chạy...")
    while True:
        try:
            ups = tg("getUpdates", offset=st["offset"], timeout=25)["result"]
            for u in ups:
                st["offset"] = u["update_id"] + 1
                if "message" in u:
                    handle(u["message"], st)
            tick(st)
            save_state(st)
        except Exception as ex:
            print("Lỗi vòng lặp:", ex, file=sys.stderr)
            time.sleep(10)


if __name__ == "__main__":
    main()

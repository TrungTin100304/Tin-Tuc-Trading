#!/usr/bin/env python3
"""Chạy MỘT lần rồi thoát (dùng với GitHub Actions chạy theo lịch).
- 07:00 mỗi sáng: tin mạnh hôm nay + lịch bảo trì FTMO hôm nay
- Trước 30 phút: tin mạnh sắp ra / FTMO sắp bảo trì
Trạng thái chống gửi trùng lưu trong state.json (workflow tự commit lại)."""
import sys
import time
from datetime import datetime

import bot

ALERT_MIN = bot.ALERT_BEFORE_MIN


def maint_line(st, en):
    end = f"{en:%H:%M}" if en.date() == st.date() else f"{en:%a %d/%m %H:%M}"
    return f"{st:%a %d/%m %H:%M} → {end}"


def main():
    if not bot.TOKEN or not bot.CHAT_ID:
        sys.exit("Thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID")
    st = bot.load_state()
    for k, v in {"ftmo_seen": [], "alerted": [], "digest_day": "", "offset": 0}.items():
        st.setdefault(k, v)
    now = datetime.now(bot.TZ)
    today = now.strftime("%Y-%m-%d")

    # --- dữ liệu (lỗi nguồn nào thì bỏ qua phần đó, lần chạy sau thử lại)
    events, wins, url = None, None, bot.FTMO_LIST
    try:
        events = bot.parse_events(bot.web_get(bot.FF_URL).json())
        bot._ff_cache.update(t=time.time(), data=events)
    except Exception as e:
        print("Lỗi lấy lịch kinh tế:", e, file=sys.stderr)
    try:
        text, url = bot.fetch_latest_ftmo()
        _, wins, raw_sec = bot.parse_ftmo_maintenance(text)
        if not wins:
            print("CẢNH BÁO: không đọc được khung giờ bảo trì. Đoạn gốc:", raw_sec[:300], file=sys.stderr)
    except Exception as e:
        print("Lỗi lấy lịch FTMO:", e, file=sys.stderr)

    # --- 1) Bản tin sáng
    if st["digest_day"] != today and (now.hour, now.minute) >= (bot.DIGEST_HOUR, bot.DIGEST_MIN) \
            and events is not None:
        msg = bot.day_digest()
        if wins is not None:
            todays = [w for w in wins if w[1] > now and (w[0].date() - now.date()).days <= 2]  # chưa kết thúc, trong 3 ngày tới
            msg += "\n\n🛠 <b>FTMO bảo trì sắp tới</b> (giờ VN)\n"
            if not wins:
                msg += "Không đọc được lịch tự động, xem bài gốc: " + url
            else:
                msg += "\n".join("• " + maint_line(*w) for w in todays) if todays else "Không có lịch bảo trì sắp tới."
            if todays:
                msg += f'\n<a href="{url}">Bài gốc</a>'
        bot.send(msg)
        st["digest_day"] = today

    # --- 2) Cảnh báo trước tin
    for e in events or []:
        left = (e["dt"] - now).total_seconds() / 60
        eid = f"{e['dt']:%Y%m%d%H%M}-{e['title']}"
        if 0 < left <= ALERT_MIN and eid not in st["alerted"]:
            bot.send(f"⏰ <b>Còn ~{int(left)} phút</b> có tin:\n{bot.fmt_event(e)}")
            st["alerted"].append(eid)

    # --- 3) Cảnh báo trước bảo trì FTMO
    for s_, e_ in wins or []:
        left = (s_ - now).total_seconds() / 60
        eid = f"ftmo-{s_:%Y%m%d%H%M}"
        if 0 < left <= ALERT_MIN and eid not in st["alerted"]:
            bot.send(f"⏰ <b>Còn ~{int(left)} phút FTMO bảo trì</b>\n🛠 {maint_line(s_, e_)} (giờ VN)\n"
                     f'Giao dịch sẽ bị tắt. <a href="{url}">Bài gốc</a>')
            st["alerted"].append(eid)

    bot.save_state(st)


if __name__ == "__main__":
    main()

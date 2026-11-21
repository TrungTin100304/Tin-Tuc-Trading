# Bot Telegram: tin kinh tế + bảo trì FTMO

## Bot làm gì
- 07:30 mỗi sáng (giờ VN): gửi tin mạnh trong ngày (CPI, FOMC/lãi suất Fed, NFP, PCE...), có dự báo và kỳ trước.
- Trước tin 30 phút: nhắn cảnh báo.
- FTMO: cứ 30 phút kiểm tra trang Trading Update; có bài mới thì gửi lịch bảo trì đã đổi sang giờ VN.
- Lệnh: `/today`, `/week`, `/ftmo`, `/help`.

## Cài đặt
1. Telegram → @BotFather → `/newbot` → lấy token.
2. Nhắn `/start` cho bot (hoặc thêm bot vào nhóm/kênh) → bot trả về Chat ID. Với kênh: thêm bot làm admin.
3. `cp .env.example .env`, điền token và chat id.
4. Chạy:
   ```
   pip install -r requirements.txt
   set -a; source .env; set +a
   python bot.py
   ```
   Chạy nền 24/7: dùng VPS rẻ + `systemd`/`pm2`/`nohup`, hoặc Railway/Fly.io.

## Lưu ý
- Giờ bảo trì FTMO ghi theo giờ MetaTrader (GMT+2 mùa đông, GMT+3 mùa hè); bot đọc "GMT+N" trong bài rồi quy đổi.
  Nếu FTMO đổi cách viết bài, bot sẽ gửi nguyên văn mục bảo trì kèm link; luôn đối chiếu bài gốc.
- Feed lịch kinh tế là bản không chính thức của Forex Factory; có thể bị giới hạn tần suất (bot chỉ gọi mỗi 30 phút).
- Bot chưa được thử với mạng thật (môi trường mình không truy cập được 2 nguồn trên), chỉ test phần phân tích dữ liệu bằng mẫu.

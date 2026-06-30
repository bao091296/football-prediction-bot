# ⚽ Bot Dự Đoán Bóng Đá Telegram

## Tính năng
- Tự động tạo poll bình chọn trước mỗi trận 12 tiếng
- Poll tự đóng 5 phút trước giờ bóng lăn
- Tính điểm tự động sau khi có kết quả
- Đồng bộ lịch thi đấu + kết quả từ football-data.org
- Admin có thể thêm trận thủ công và cập nhật kết quả

## Cài đặt

### 1. Clone và cài thư viện
```bash
cd football-prediction-bot
pip install -r requirements.txt
```

### 2. Tạo file .env
```bash
cp .env.example .env
# Chỉnh sửa .env với thông tin của bạn
```

### 3. Lấy Token & API Key
- **Bot Token**: Nhắn tin với [@BotFather](https://t.me/BotFather) → `/newbot`
- **Admin ID**: Nhắn tin với [@userinfobot](https://t.me/userinfobot) để lấy ID của bạn
- **Football API**: Đăng ký miễn phí tại [football-data.org](https://www.football-data.org/client/register)

### 4. Thêm bot vào group Telegram
- Thêm bot vào group của bạn
- Cấp quyền **Admin** cho bot (để gửi poll)
- Gõ `/start` trong group

### 5. Chạy bot
```bash
python bot.py
```

---

## Lệnh người dùng
| Lệnh | Mô tả |
|------|-------|
| `/start` | Đăng ký + xem hướng dẫn |
| `/diem` | Bảng xếp hạng điểm |
| `/dudoan` | Lịch sử dự đoán của bạn |
| `/trandau` | Các trận sắp tới |
| `/help` | Hướng dẫn chi tiết |

## Lệnh Admin
| Lệnh | Mô tả |
|------|-------|
| `/them_tran TênNhà vs TênKhách dd/mm/yyyy HH:MM [Giải]` | Thêm trận thủ công |
| `/tao_poll <match_id>` | Tạo poll ngay cho một trận |
| `/cap_nhat <match_id> <bàn_nhà> <bàn_khách>` | Cập nhật kết quả + tính điểm |
| `/dong_bo` | Đồng bộ lịch từ API thủ công |
| `/admin` | Xem danh sách lệnh admin |

---

## Cách tính điểm
- **Đoán đúng**: `+(tổng điểm thua ÷ số người đúng)`
- **Đoán sai**: `-50 điểm`
- **Không đoán**: `-50 điểm` (coi như thua)

**Ví dụ**: 3 đúng, 5 sai, 2 không đoán  
→ Tổng thua = 7 × 50 = 350 điểm  
→ Mỗi người đúng được: 350 ÷ 3 ≈ **116.7 điểm**

---

## Các giải đấu hỗ trợ (football-data.org Free Tier)
| Code | Giải |
|------|------|
| `PL` | Premier League |
| `CL` | UEFA Champions League |
| `WC` | FIFA World Cup |
| `PD` | La Liga |
| `BL1` | Bundesliga |
| `SA` | Serie A |
| `FL1` | Ligue 1 |
| `EC` | UEFA European Championship |

---

## Chạy bằng systemd (Linux server)
```ini
# /etc/systemd/system/football-bot.service
[Unit]
Description=Football Prediction Telegram Bot
After=network.target

[Service]
WorkingDirectory=/path/to/football-prediction-bot
ExecStart=/usr/bin/python3 bot.py
Restart=always
User=your_user

[Install]
WantedBy=multi-user.target
```
```bash
systemctl enable football-bot
systemctl start football-bot
```

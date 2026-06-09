# LINE Bot ที่ปรึกษาและผู้เชี่ยวชาญประจำกลุ่มไลน์ (LINE Expert Advisor Bot)

บอทสำหรับแอปพลิเคชัน LINE ที่ใช้โมเดลภาษาจาก OpenAI (ChatGPT) ทำหน้าที่เสมือนเป็นผู้เชี่ยวชาญและที่ปรึกษาในกลุ่มไลน์ ตอบคำถามเฉพาะเมื่อถูกเรียกใช้งาน เพื่อไม่ให้รบกวนบทสนทนาทั่วไปของสมาชิกในกลุ่ม

---

## 🛠️ ขั้นตอนการติดตั้งและการตั้งค่าระบบ

### 1. การตั้งค่าบน LINE Developers Console
ก่อนเริ่มใช้งาน คุณจำเป็นต้องสร้าง Channel บน [LINE Developers Console](https://developers.line.biz/) และรับข้อมูลสำคัญดังนี้:

1. **สร้าง Provider และ Messaging API Channel**
2. **Channel Secret**: คัดลอกค่าจากแท็บ *Basic settings*
3. **Channel Access Token**: ไปที่แท็บ *Messaging API* แล้วกด Issue โทเคนขึ้นมา
4. **เปิดการใช้งานในกลุ่มไลน์**:
   - ในแท็บ *Messaging API* เลื่อนหาหัวข้อ **"Allow bot to join groups & multi-person chats"**
   - เปลี่ยนสถานะให้เป็น **Enabled**
5. **ปิดการตอบกลับอัตโนมัติ**:
   - ปิด **Auto-reply messages** (หากเปิดไว้ LINE จะตอบกลับด้วยข้อความเริ่มต้นของระบบ)
   - เปิดการใช้งาน **Webhooks**

---

### 2. การตั้งค่าโปรเจกต์ภายในเครื่อง (Local Setup)

1. คัดลอกไฟล์ `.env.example` ไปเป็นไฟล์จริงชื่อ `.env`:
   ```bash
   cp .env.example .env
   ```
2. แก้ไขข้อมูลในไฟล์ `.env` ด้วยโทเคนและรหัสผ่านจริงของคุณ:
   ```env
   LINE_CHANNEL_ACCESS_TOKEN=ใส่_Channel_Access_Token_ของคุณตรงนี้
   LINE_CHANNEL_SECRET=ใส่_Channel_Secret_ของคุณตรงนี้
   OPENAI_API_KEY=ใส่_OpenAI_API_Key_ของคุณตรงนี้
   PORT=5000
   ```

3. ติดตั้งไลบรารีที่จำเป็น:
   ```bash
   pip install -r requirements.txt
   ```

4. รันแอปพลิเคชันภายในเครื่อง (สำหรับทดสอบ):
   ```bash
   python line-bot.py
   ```

---

### 3. การนำไปติดตั้งบนคลาวด์ (Deployment on Render)

เนื่องจาก LINE บังคับใช้งาน Webhook ผ่านโปรโตคอล HTTPS เราจึงต้องนำโค้ดนี้ไปรันบนเซิร์ฟเวอร์ที่เข้าถึงได้จากภายนอก เช่น [Render](https://render.com/) (ฟรี):

1. สร้างโปรเจกต์ประเภท **Web Service** บน Render และเชื่อมต่อกับ GitHub Repository นี้
2. เลือก Runtime เป็น **Python**
3. ตั้งค่าคำสั่งในแต่ละส่วนดังนี้:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn line-bot:app`
4. เพิ่ม **Environment Variables** ในแถบการตั้งค่าบน Render:
   - `LINE_CHANNEL_ACCESS_TOKEN`
   - `LINE_CHANNEL_SECRET`
   - `OPENAI_API_KEY`
5. นำ URL ที่ได้จาก Render (เช่น `https://your-app.onrender.com/callback`) ไปใส่ในช่อง **Webhook URL** บน LINE Developers Console แล้วกดบันทึกและคลิกปุ่ม **Verify** เพื่อทดสอบความเชื่อมโยง

---

## 💬 วิธีการสั่งงานบอทในกลุ่มไลน์

เพื่อป้องกันไม่ให้บอทคอยตอบแทรกประโยคการสนทนาทั่วไปในกลุ่ม บอทจะเลือกตอบกลับเฉพาะสองกรณีนี้เท่านั้น:

1. **คุยแบบตัวต่อตัว (1-on-1 Chat)**: บอทจะตอบกลับข้อมูลทุกประโยคที่ส่งหาบอทโดยตรง
2. **ในกลุ่มไลน์ (Group Chat)**: บอทจะประมวลผลคำแนะนำเฉพาะข้อความที่นำหน้าด้วยคีย์เวิร์ดต่อไปนี้:
   - `บอท` หรือ `bot` หรือ `@bot`
   - `ที่ปรึกษา`
   - `ช่วยแนะนำ`
   - `ช่วยบอกหน่อย`

**ตัวอย่างเช่น:**
* "บอท: วางแผนการเดินทางไปเชียงใหม่ 3 วัน 2 คืน ให้หน่อย"
* "ที่ปรึกษา ช่วยอธิบายทฤษฎีแรงโน้มถ่วงแบบเข้าใจง่าย ๆ หน่อยครับ"

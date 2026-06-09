import os
import sys
from flask import Flask, request, abort
from dotenv import load_dotenv

# โหลดตัวแปรสภาพแวดล้อมจากไฟล์ .env
load_dotenv()

# ดึงค่าคอนฟิกเกอเรชัน
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

app = Flask(__name__)

# ตรวจสอบตัวแปรที่จำเป็นใน Log
if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET or not OPENAI_API_KEY:
    app.logger.warning("คำเตือน: ตัวแปร LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET หรือ OPENAI_API_KEY ยังไม่ได้กำหนดค่า")

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from openai import OpenAI

# เริ่มต้นไลบรารีและอ็อบเจกต์ที่จำเป็น
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN or "")
handler = WebhookHandler(LINE_CHANNEL_SECRET or "")
openai_client = OpenAI(api_key=OPENAI_API_KEY or "dummy_key")

# กำหนด System Prompt ของ ChatGPT ให้สวมบทบาทเป็นผู้เชี่ยวชาญ/ที่ปรึกษา
SYSTEM_PROMPT = """คุณเป็นผู้เชี่ยวชาญและที่ปรึกษามืออาชีพที่มีความรอบรู้และชาญฉลาด (Professional Consultant & Advisor) 
หน้าที่ของคุณคือช่วยตอบคำถามและให้คำแนะนำที่มีประโยชน์ มีเหตุมีผล สุภาพ และเชื่อถือได้แก่สมาชิกในกลุ่มไลน์
โปรดตอบกลับเป็นภาษาไทยอย่างเป็นมิตร กระชับ ตรงประเด็น และเข้าใจง่าย โดยคำนึงถึงบริบทที่ผู้ใช้ถาม"""

@app.route("/callback", methods=['POST'])
def callback():
    # รับ Signature จาก LINE Header สำหรับยืนยันตัวตนความปลอดภัย
    signature = request.headers.get('X-Line-Signature')

    # รับข้อมูล Request Body
    body = request.get_data(as_text=True)

    # ส่งต่อให้ Webhook Handler ตรวจสอบและประมวลผล
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("Signature ไม่ถูกต้อง กรุณาตรวจสอบ Channel Access Token/Channel Secret")
        abort(400)

    return 'OK'

def ask_openai(question: str) -> str:
    """ฟังก์ชันส่งคำถามไปยัง OpenAI (ChatGPT)"""
    try:
        # ใช้โมเดล gpt-4o-mini ที่ราคาถูกและตอบได้รวดเร็ว เหมาะสำหรับการใช้งานทั่วไป
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question}
            ],
            max_tokens=800,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        app.logger.error(f"OpenAI API Error: {e}")
        return f"ขออภัยครับ เกิดข้อผิดพลาดในการประมวลผลคำแนะนำ: {str(e)}"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_message = event.message.text
    source_type = event.source.type  # 'user', 'group', หรือ 'room'
    
    # รายการคำสั่งเรียกบอทในกลุ่มไลน์ เพื่อไม่ให้ตอบแทรกการคุยปกติของสมาชิก
    prefixes = ['บอท', 'bot', '@bot', 'ที่ปรึกษา', 'ช่วยแนะนำ', 'ช่วยบอกหน่อย']
    
    should_respond = False
    cleaned_message = user_message.strip()
    
    if source_type == 'user':
        # แชทแบบ 1-on-1 ตอบกลับทุกข้อความ
        should_respond = True
    else:
        # แชทในกลุ่มหรือห้องสนทนา ตอบกลับเฉพาะเมื่อมีคำนำหน้าที่กำหนดไว้
        for prefix in prefixes:
            if cleaned_message.lower().startswith(prefix.lower()):
                should_respond = True
                # ลบคำนำหน้าออกเพื่อให้ถาม OpenAI เฉพาะคำถามหลัก
                cleaned_message = cleaned_message[len(prefix):].strip()
                # ลบอักขระเชื่อมต่อ เช่น เครื่องหมายโคลอน (:) หรือ ลูกน้ำ (,) ที่ผู้ใช้อาจพิมพ์ตามหลัง
                if cleaned_message.startswith(':') or cleaned_message.startswith(',') or cleaned_message.startswith(' '):
                    cleaned_message = cleaned_message[1:].strip()
                break
                
    if should_respond:
        if not cleaned_message:
            # กรณีผู้ใช้พิมพ์แค่คำเรียกบอท เช่น "บอท" ให้แนะนำวิธีใช้
            reply_text = "สวัสดีครับ! ผมคือผู้เชี่ยวชาญ/ที่ปรึกษาประจำกลุ่มนี้ ยินดีให้คำปรึกษาและคำแนะนำในด้านต่าง ๆ ครับ มีเรื่องอะไรอยากให้ช่วยเหลือ สามารถถามเข้ามาได้เลยครับ!"
        else:
            # ส่งไปถาม ChatGPT
            reply_text = ask_openai(cleaned_message)
            
        # ตอบกลับข้อความไปยัง LINE
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )

if __name__ == "__main__":
    # รันเซิร์ฟเวอร์ Flask
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

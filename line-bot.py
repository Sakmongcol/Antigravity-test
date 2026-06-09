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
    MessagingApiBlob,
    ReplyMessageRequest,
    TextMessage,
    ImageMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FileMessageContent
from openai import OpenAI
import io
import re
import urllib.parse
from pypdf import PdfReader
from youtube_transcript_api import YouTubeTranscriptApi

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

def extract_youtube_video_id(url: str) -> str:
    """ฟังก์ชันสกัด Video ID ออกจากลิงก์ YouTube รูปแบบต่าง ๆ"""
    pattern = r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|\S*?[?&]v=)|youtu\.be\/)([a-zA-Z0-9_-]{11})'
    match = re.search(pattern, url)
    return match.group(1) if match else None

def summarize_youtube_video(video_id: str) -> str:
    """ฟังก์ชันดึงคำบรรยายวิดีโอ YouTube และสรุปผลด้วย OpenAI"""
    try:
        # ดึงข้อมูลรายการคำบรรยายทั้งหมดของวิดีโอ
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        # ค้นหาคำบรรยายภาษาไทยก่อน หากไม่มีให้ใช้ภาษาอังกฤษ หากไม่มีอีกให้ใช้ตัวเลือกแรกสุดที่มี
        try:
            transcript = transcript_list.find_transcript(['th'])
        except Exception:
            try:
                transcript = transcript_list.find_transcript(['en'])
            except Exception:
                # เลือกตัวแรกสุดที่มีในรายการคำบรรยาย (เช่น ภาษาอื่น ๆ)
                transcript = next(iter(transcript_list))
                
        # ดึงบทพูดและรวบรวมเป็นข้อความยาวชุดเดียว
        transcript_data = transcript.fetch()
        full_text = " ".join([item['text'] for item in transcript_data])
        
        # จำกัดเนื้อหาให้อยู่ในขอบเขต 20,000 ตัวอักษร เพื่อประหยัดค่าบริการ API
        max_chars = 20000
        if len(full_text) > max_chars:
            full_text = full_text[:max_chars] + "\n...(เนื้อหาบทสนทนาส่วนที่เหลือถูกตัดออกเนื่องจากยาวเกินโควตา)..."
            
        # กำหนด Prompt สำหรับสั่งการ ChatGPT ในการสรุปและแปลเป็นภาษาไทย
        prompt = (
            "คุณเป็นผู้เชี่ยวชาญในการสรุปเนื้อหาวิดีโอ หน้าที่ของคุณคือการสรุปข้อมูลเนื้อหาจากวิดีโอ YouTube นี้เป็นภาษาไทย "
            "โดยการสรุปจะต้องกระชับ ตรงประเด็น และครอบคลุมเนื้อหาสำคัญทั้งหมด แบ่งโครงสร้างออกเป็นหัวข้อหลักๆ ที่เข้าใจง่าย "
            "หากบทสนทนาในวิดีโอเป็นภาษาต่างประเทศ ให้แปลและเรียบเรียงออกมาเป็นภาษาไทยที่ถูกต้อง สละสลวย:\n\n"
            f"เนื้อหาบทสนทนาในวิดีโอ:\n{full_text}"
        )
        
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a professional video content summarizer and translator."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1000,
            temperature=0.5
        )
        return response.choices[0].message.content.strip()
        
    except Exception as e:
        err_msg = str(e)
        if "No transcripts were found" in err_msg or "Subtitles are disabled" in err_msg:
            return "ไม่พบคำบรรยาย (Subtitles/Captions) ในวิดีโอ YouTube นี้ครับ ทำให้ไม่สามารถสกัดข้อความเสียงเพื่อมาสรุปเนื้อหาได้"
        return f"ขออภัยครับ เกิดข้อผิดพลาดในการดาวน์โหลดคำบรรยายวิดีโอ: {err_msg}"


def extract_youtube_video_id(url: str) -> str:
    """Extract a YouTube video ID from common YouTube URL formats."""
    url_candidates = re.findall(r'(?:https?://)?(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)/[^\s<>"\']+', url)
    for candidate in url_candidates:
        normalized = candidate if candidate.startswith(("http://", "https://")) else f"https://{candidate}"
        parsed = urllib.parse.urlparse(normalized)
        host = parsed.netloc.lower()
        path_parts = [part for part in parsed.path.split("/") if part]

        if host.endswith("youtu.be") and path_parts:
            video_id = path_parts[0]
            if re.fullmatch(r"[a-zA-Z0-9_-]{11}", video_id):
                return video_id

        if host.endswith("youtube.com"):
            query_video_id = urllib.parse.parse_qs(parsed.query).get("v", [None])[0]
            if query_video_id and re.fullmatch(r"[a-zA-Z0-9_-]{11}", query_video_id):
                return query_video_id

            if len(path_parts) >= 2 and path_parts[0] in {"shorts", "live", "embed", "v"}:
                video_id = path_parts[1]
                if re.fullmatch(r"[a-zA-Z0-9_-]{11}", video_id):
                    return video_id

    patterns = [
        r'(?:https?://)?(?:www\.|m\.)?youtube\.com/watch\?(?:[^#\s]*&)?v=([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?(?:www\.|m\.)?youtube\.com/(?:shorts|live|embed|v)/([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?youtu\.be/([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def has_youtube_link(text: str) -> bool:
    """Return True when text appears to contain a YouTube link."""
    return re.search(r'(?:youtube\.com|youtu\.be)', text, re.IGNORECASE) is not None


def _transcript_items_to_text(transcript_data) -> str:
    """Normalize transcript rows from old/new youtube-transcript-api versions."""
    chunks = []
    for item in transcript_data:
        if isinstance(item, dict):
            text = item.get("text", "")
        else:
            text = getattr(item, "text", "")
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            chunks.append(text)
    return " ".join(chunks)


def _fetch_best_youtube_transcript(video_id: str) -> tuple[str, str]:
    """Fetch Thai first, then English, then any available transcript."""
    transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

    try:
        transcript = transcript_list.find_transcript(["th"])
    except Exception:
        try:
            transcript = transcript_list.find_transcript(["en"])
        except Exception:
            transcript = next(iter(transcript_list))

    language = getattr(transcript, "language_code", "unknown")
    return _transcript_items_to_text(transcript.fetch()), language


def summarize_youtube_video(video_id: str) -> str:
    """Summarize a YouTube video transcript concisely in Thai."""
    try:
        full_text, language = _fetch_best_youtube_transcript(video_id)

        if not full_text:
            return "ไม่พบข้อความคำบรรยายในคลิปนี้ จึงยังสรุปเนื้อหาให้ไม่ได้ครับ"

        max_chars = 24000
        was_truncated = len(full_text) > max_chars
        if was_truncated:
            full_text = full_text[:max_chars]

        prompt = f"""
อ่าน transcript ของคลิป YouTube แล้วสรุปและวิเคราะห์ออกมาเป็นภาษาไทยเท่านั้น

ให้ตอบเป็นโครงสร้างนี้:
1. สรุปสั้น ๆ: อธิบายใจความหลักของคลิปใน 2-4 ประโยค
2. ประเด็นสำคัญ: bullet สั้น ๆ ครอบคลุมเนื้อหาหลัก
3. วิเคราะห์/ข้อสังเกต: อธิบายความหมาย ผลกระทบ หรือสิ่งที่ผู้ชมควรเข้าใจจากเนื้อหา
4. สิ่งที่นำไปใช้ได้: bullet สั้น ๆ ถ้ามีประเด็นเชิงปฏิบัติ

ข้อกำหนด:
- ถ้าต้นฉบับเป็นภาษาต่างประเทศ ให้แปลและเรียบเรียงเป็นภาษาไทยธรรมชาติ
- ห้ามใส่ข้อมูลที่ไม่มีอยู่ใน transcript
- ถ้า transcript ไม่พอสำหรับวิเคราะห์ ให้บอกตามตรงและวิเคราะห์เฉพาะจากข้อมูลที่มี
- จัดรูปแบบอ่านง่ายสำหรับ LINE
- ความยาวรวมไม่เกินประมาณ 3,500 ตัวอักษร

ภาษา transcript ที่เลือกใช้: {language}
หมายเหตุ: transcript {'ถูกตัดบางส่วนเพราะยาวมาก' if was_truncated else 'ถูกส่งครบตามที่ดึงได้'}

Transcript:
{full_text}
""".strip()

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You summarize and translate video transcripts into concise, accurate Thai."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1200,
            temperature=0.3
        )
        summary = response.choices[0].message.content.strip()
        if len(summary) > 4500:
            summary = summary[:4450].rstrip() + "\n\n...(ตัดให้สั้นลงเพื่อให้ส่งใน LINE ได้)"
        return summary

    except Exception as e:
        err_msg = str(e)
        if "No transcripts were found" in err_msg or "Subtitles are disabled" in err_msg or "TranscriptsDisabled" in err_msg:
            return "ไม่พบคำบรรยาย/Subtitles ในคลิป YouTube นี้ จึงยังไม่สามารถสรุปจากเสียงของคลิปได้ครับ"
        if "VideoUnavailable" in err_msg:
            return "เปิดคลิป YouTube นี้ไม่ได้ครับ อาจเป็นคลิปส่วนตัว ถูกลบ หรือจำกัดการเข้าถึง"
        app.logger.error(f"YouTube transcript summary error: {e}")
        return f"ขออภัยครับ เกิดข้อผิดพลาดในการสรุปคลิป YouTube: {err_msg}"


def is_youtube_summary_error(reply_text: str) -> bool:
    """Return True when the YouTube summary result is an error/status message."""
    error_starts = (
        "ไม่พบ",
        "เปิดคลิป",
        "ขออภัย",
        "à¹„à¸¡à¹ˆ",
        "à¸‚à¸­à¸­à¸ à¸±à¸¢",
    )
    return reply_text.startswith(error_starts)


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
                
    # ตรวจสอบว่าในข้อความดิบมีลิงก์ YouTube หรือไม่
    youtube_id = extract_youtube_video_id(user_message)
    youtube_link_seen = has_youtube_link(user_message)
    
    is_youtube_request = False
    if youtube_id:
        is_youtube_request = True
    if False:
        if source_type == 'user':
            is_youtube_request = True
        else:
            # ในกลุ่มไลน์: ตอบสนองหากมีคำสั่งเรียกบอทนำหน้า หรือหากข้อความประกอบด้วยลิงก์เดี่ยวๆ ล้วนๆ
            is_only_link = re.match(r'^https?:\/\/(?:www\.)?(?:youtube\.com|youtu\.be)\/\S+$', cleaned_message) is not None
            if should_respond or is_only_link:
                is_youtube_request = True

    if is_youtube_request:
        # ส่งข้อความสรุปคลิปวิดีโอ YouTube
        reply_text = summarize_youtube_video(youtube_id)
        # เติมหัวเรื่องระบุความพร้อม
        if not is_youtube_summary_error(reply_text):
            reply_text = f"สรุปและวิเคราะห์คลิป YouTube:\n\n{reply_text}"
            
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )
    elif youtube_link_seen:
        reply_text = "ผมเห็นลิงก์ YouTube แล้วครับ แต่ยังอ่าน Video ID ไม่ได้ รบกวนส่งลิงก์แบบเต็ม เช่น https://www.youtube.com/watch?v=XXXXXXXXXXX หรือ https://youtu.be/XXXXXXXXXXX"
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )
    elif should_respond:
        # ตรวจสอบเพิ่มเติมว่าต้องการสร้างรูปภาพหรืออินโฟกราฟิกหรือไม่
        is_image_request = False
        image_prompt = ""
        image_prefixes = ['วาดรูป', 'สร้างภาพ', 'อินโฟกราฟิก', 'อินโฟกราฟฟิก', 'อินโฟ']
        
        for img_pref in image_prefixes:
            if cleaned_message.lower().startswith(img_pref.lower()):
                is_image_request = True
                image_prompt = cleaned_message[len(img_pref):].strip()
                if image_prompt.startswith(':') or image_prompt.startswith(',') or image_prompt.startswith(' '):
                    image_prompt = image_prompt[1:].strip()
                break

        if is_image_request:
            if not image_prompt:
                reply_text = "กรุณาระบุรายละเอียดรูปภาพที่คุณต้องการให้วาดด้วยครับ เช่น 'อินโฟกราฟิก ขั้นตอนการออมเงิน'"
                with ApiClient(configuration) as api_client:
                    line_bot_api = MessagingApi(api_client)
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=reply_text)]
                        )
                    )
            else:
                # ตกแต่ง Prompt ให้เน้นสไตล์อินโฟกราฟิกตามที่ผู้ใช้กำหนด
                styled_prompt = f"{image_prompt}, flat vector infographic design, professional clean presentation, charts and diagrams, minimal icons, structured educational layout"
                encoded_prompt = urllib.parse.quote(styled_prompt)
                
                # ลิงก์สำหรับดึงภาพผลลัพธ์จาก Pollinations.ai (ไม่มีลายน้ำและฟรี 100%)
                image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&private=true"
                
                # ส่งทั้งข้อความสถานะและรูปภาพกลับไปพร้อมกันในชุดเดียว
                status_text = f"🎨 กำลังสร้างภาพอินโฟกราฟิกเกี่ยวกับ: '{image_prompt}'\nกรุณารอสักครู่เพื่อโหลดรูปภาพ..."
                
                with ApiClient(configuration) as api_client:
                    line_bot_api = MessagingApi(api_client)
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                TextMessage(text=status_text),
                                ImageMessage(original_content_url=image_url, preview_image_url=image_url)
                            ]
                        )
                    )
        else:
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
@handler.add(MessageEvent, message=FileMessageContent)
def handle_file(event):
    message_id = event.message.id
    file_name = event.message.file_name
    
    # ดึงนามสกุลไฟล์เพื่อตรวจสอบว่าเป็น PDF หรือไม่
    if not file_name.lower().endswith('.pdf'):
        reply_text = f"ระบบรองรับการอ่านและสรุปเฉพาะไฟล์ PDF เท่านั้นครับ (คุณส่งไฟล์: {file_name})"
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )
        return

    try:
        # ดาวน์โหลดไฟล์ PDF จาก LINE
        with ApiClient(configuration) as api_client:
            messaging_blob_api = MessagingApiBlob(api_client)
            message_content = messaging_blob_api.get_message_content(message_id)
            
            # แปลงข้อมูลไบนารีและสกัดข้อความ
            if hasattr(message_content, 'read'):
                pdf_data = message_content.read()
            else:
                pdf_data = message_content
                
            pdf_bytes = io.BytesIO(pdf_data)
            reader = PdfReader(pdf_bytes)
            
            pdf_text = ""
            for page in reader.pages:
                pdf_text += page.extract_text() or ""
                
            pdf_text = pdf_text.strip()
            
            if not pdf_text:
                reply_text = f"ไม่สามารถสกัดข้อความออกจากไฟล์ PDF '{file_name}' นี้ได้ครับ เอกสารอาจเป็นสแกนรูปภาพล้วนที่ไม่มีเลเยอร์ข้อความ"
            else:
                # จำกัดขนาดข้อความสำหรับส่งให้ OpenAI (เพื่อไม่ให้ค่าบริการสูงเกินไป)
                max_chars = 20000
                if len(pdf_text) > max_chars:
                    pdf_text = pdf_text[:max_chars] + "\n...(ข้อความส่วนที่เหลือถูกตัดออกเนื่องจากเกินโควตาเนื้อหา)..."
                
                # เรียกใช้งาน ChatGPT เพื่อทำการสรุปเอกสาร
                prompt = f"กรุณาสรุปเนื้อหาสำคัญจากเอกสาร PDF นี้เป็นภาษาไทยอย่างกระชับตรงประเด็น และเข้าใจง่าย โดยแยกเป็นหัวข้อสำคัญหลักๆ:\n\n{pdf_text}"
                summary = ask_openai(prompt)
                
                reply_text = f"📄 สรุปเนื้อหาไฟล์เอกสาร: {file_name}\n\n{summary}"
                
            # ส่งคำตอบกลับหาผู้ใช้
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )
            
    except Exception as e:
        app.logger.error(f"Error processing PDF: {e}")
        reply_text = f"ขออภัยครับ เกิดข้อผิดพลาดในการโหลดหรืออ่านไฟล์ PDF: {str(e)}"
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

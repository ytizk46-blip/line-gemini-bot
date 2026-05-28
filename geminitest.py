import os
import logging
import threading
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
from google import genai
from google.genai import types

# ログの設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# 環境変数の読み込み
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# 起動チェック
if not all([LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, GEMINI_API_KEY]):
    logger.warning("環境変数 (LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, GEMINI_API_KEY) の一部が不足しています。ローカル開発やデプロイ時に必ず設定してください。")

# 各種APIクライアントの初期化 (環境変数がある場合のみ)
line_bot_api = None
handler = None
client = None

if LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET and GEMINI_API_KEY:
    line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
    handler = WebhookHandler(LINE_CHANNEL_SECRET)
    client = genai.Client(api_key=GEMINI_API_KEY)


# --- スレッドセーフな会話履歴マネージャー ---
class ChatHistoryManager:
    def __init__(self, max_history_len=10):
        self.histories = {}
        self.lock = threading.Lock()
        self.max_history_len = max_history_len

    def get(self, user_id):
        with self.lock:
            if user_id not in self.histories:
                self.histories[user_id] = []
            # 処理中の書き換えを防ぐため、コピーを返す
            return list(self.histories[user_id])

    def save(self, user_id, history):
        with self.lock:
            # 履歴の長さを制限
            if len(history) > self.max_history_len:
                history = history[-self.max_history_len:]
            self.histories[user_id] = history
            
            # メモリリーク防止のため、登録ユーザー数が多すぎる場合は古いデータから削除
            if len(self.histories) > 2000:
                oldest_key = next(iter(self.histories))
                del self.histories[oldest_key]

history_manager = ChatHistoryManager(max_history_len=10) # 過去5往復（ユーザー5回、モデル5回）まで保持


# --- 非同期でGeminiを呼び出し、LINEに返信する処理 ---
def process_and_reply(reply_token, user_id, message_text=None, image_bytes=None, mime_type=None):
    if not client or not line_bot_api:
        logger.error("APIクライアントが初期化されていません。")
        return

    # 会話履歴の取得
    history = history_manager.get(user_id)

    # 今回の入力を構成
    parts = []
    if image_bytes:
        parts.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))
    if message_text:
        parts.append(types.Part.from_text(text=message_text))

    if not parts:
        logger.warning("処理すべきテキストまたは画像が見つかりません。")
        return

    # ユーザーの発言を履歴に追加
    user_content = types.Content(role='user', parts=parts)
    history.append(user_content)

    try:
        # キャラクターや返答ルールの指示（システムインストラクション）
        config = types.GenerateContentConfig(
            system_instruction="あなたはLINEで稼働する親切でフレンドリーなAIアシスタントです。絵文字を交えながら、日本語で親しみやすく返答してください。"
        )

        # Gemini APIを呼び出し（履歴全体を渡すことで文脈を考慮させる）
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=history,
            config=config
        )
        reply_text = response.text

        # モデルの応答を履歴に追加して保存
        model_content = types.Content(role='model', parts=[types.Part.from_text(text=reply_text)])
        history.append(model_content)
        history_manager.save(user_id, history)

    except Exception as e:
        logger.error(f"Gemini APIでの応答生成中にエラーが発生しました: {e}")
        reply_text = "申し訳ありません。回答を作成中にエラーが発生しました。時間をおいて再度お試しください。"

    # LINEへのメッセージ返信
    try:
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text=reply_text)
        )
    except Exception as e:
        logger.error(f"LINEへの返信送信中にエラーが発生しました: {e}")


# --- Flaskルート設定 ---
@app.route("/")
def home():
    return "LINE Gemini Bot is running!"

@app.route("/callback", methods=['POST'])
def callback():
    if not handler:
        logger.error("WebhookHandlerが初期化されていません。環境変数を確認してください。")
        abort(500)

    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    logger.info(f"Request body: {body}")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logger.error("署名の検証に失敗しました。チャネルシークレットなどを確認してください。")
        abort(400)

    return 'OK'


# --- LINEイベントハンドラー ---

# 1. テキストメッセージ受信時
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    reply_token = event.reply_token
    user_id = event.source.user_id
    user_message = event.message.text

    # バックグラウンドスレッドで処理を実行し、LINE Webhookには即座に200 OKを返す（5秒タイムアウト対策）
    thread = threading.Thread(
        target=process_and_reply,
        args=(reply_token, user_id),
        kwargs={'message_text': user_message}
    )
    thread.daemon = True
    thread.start()


# 2. 画像メッセージ受信時
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    reply_token = event.reply_token
    user_id = event.source.user_id
    message_id = event.message.id

    if not line_bot_api:
        logger.error("LineBotApiが初期化されていません。")
        return

    # 画像データをLINEサーバーから取得
    try:
        message_content = line_bot_api.get_message_content(message_id)
        image_bytes = message_content.content
    except Exception as e:
        logger.error(f"LINEからの画像取得に失敗しました: {e}")
        try:
            line_bot_api.reply_message(
                reply_token,
                TextSendMessage(text="画像の読み込みに失敗しました。もう一度送信してください。")
            )
        except Exception as reply_err:
            logger.error(f"エラー通知の送信に失敗しました: {reply_err}")
        return

    # バックグラウンドスレッドで画像解析を処理し、Webhookには即座に200 OKを返す
    thread = threading.Thread(
        target=process_and_reply,
        args=(reply_token, user_id),
        kwargs={
            'message_text': "画像が送信されました。何が写っているか説明するか、画像についての質問に答えてください。",
            'image_bytes': image_bytes,
            'mime_type': "image/jpeg"
        }
    )
    thread.daemon = True
    thread.start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

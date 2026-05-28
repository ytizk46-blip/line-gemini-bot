# LINE Gemini Bot (高度機能版)

最新の公式 Google Gemini SDK (`google-genai`) と LINE Bot を組み合わせた、対話型のAIチャットボットです。

## 主な機能

1. **タイムアウト対策（非同期スレッド処理）**
   LINEのWebhookは「5秒以内」にレスポンスを返す必要があります。このボットはメッセージ受信後、Geminiの処理を別スレッドで開始し、即座にLINE側に `200 OK` を応答するため、処理遅延による二重返信やエラーを防ぎます。
2. **会話履歴（コンテキスト）の維持**
   メモリ上でユーザーごとに過去5往復（最大10ターン）の会話履歴を保持します。文脈を理解した対話（マルチターンチャット）が可能です。
3. **画像解析（マルチモーダル）対応**
   LINEで画像が送信された場合、ボットがその画像を自動で取得し、Geminiに引き渡して画像を解説したり質問に答えたりします。会話履歴に画像データが残るため、「この画像に写っているものは何？」の後に「その色は何ですか？」とテキストで重ねて質問しても、Geminiは前の画像を考慮して回答できます。

## 準備するもの

1. **GitHubアカウント**（コード管理用）
2. **LINE Developersアカウント**
   - Messaging APIチャネルの作成
   - 「チャネルアクセストークン（長期）」の発行
   - 「チャネルシークレット」の確認
3. **Google AI Studioアカウント**
   - Gemini APIキーの取得（`GEMINI_API_KEY`）

## セットアップとローカル起動方法

### 1. 必要パッケージのインストール

```bash
pip install -r requirements.txt
```

### 2. 環境変数の設定

以下の環境変数をシステムまたは起動元のシェルに設定してください。

**Windows (PowerShell):**
```powershell
$env:LINE_CHANNEL_ACCESS_TOKEN="あなたのLINEチャネルアクセストークン"
$env:LINE_CHANNEL_SECRET="あなたのLINEチャネルシークレット"
$env:GEMINI_API_KEY="あなたのGemini APIキー"
```

**Mac / Linux:**
```bash
export LINE_CHANNEL_ACCESS_TOKEN="あなたのLINEチャネルアクセストークン"
export LINE_CHANNEL_SECRET="あなたのLINEチャネルシークレット"
export GEMINI_API_KEY="あなたのGemini APIキー"
```

### 3. アプリケーションの起動

```bash
python geminitest.py
```
デフォルトでは `http://localhost:5000` でサーバーが起動します。

### 4. 外部公開（ローカルテスト用）

LINE DevelopersのWebhookに登録するためには、ローカルサーバーをHTTPSで外部公開する必要があります。`ngrok` などのツールを使うと便利です。

```bash
ngrok http 5000
```
発行された `https://xxxx.ngrok-free.app/callback` を LINE Developersの「Webhook URL」に登録し、「Webhookの利用」をONにしてください。

---

## 本番デプロイについて

Render, Heroku, Fly.io, Cloud Run などのコンテナ/PaaS環境に簡単にデプロイできます。

- 本番用の起動コマンドには `gunicorn` を推奨します：
  ```bash
  gunicorn geminitest:app
  ```
- デプロイ先のダッシュボードで、環境変数 `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_CHANNEL_SECRET`, `GEMINI_API_KEY` を必ず設定してください。

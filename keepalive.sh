#!/bin/bash
# Streamlit + cloudflared 임시 터널 keep-alive 워치독.
# 둘 중 하나라도 죽으면 자동 재기동. 현재 공개 URL은 /tmp/cf-url.txt 에 기록.
cd /home/junee/workspace/ubuntu/ai-compete-streamlit || exit 1
ENVF=/home/junee/workspace/ubuntu/ai_trading_research/.env.local
# .env.local 의 키를 export (DART + LLM 4종)
set -a
for K in DART_API_KEY OPENFIGI_API_KEY OPENAI_API_KEY GOOGLE_GENERATIVE_AI_API_KEY ANTHROPIC_API_KEY PERPLEXITY_API_KEY; do
  V=$(grep -E "^$K=" "$ENVF" | cut -d= -f2- | tr -d '\r\n ')
  [ -n "$V" ] && export "$K=$V"
done
set +a
export SEC_USER_AGENT="ai-compete research namhojun@gmail.com"

start_streamlit() {
  PID=$(ss -ltnp 2>/dev/null | grep ':8501 ' | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2)
  [ -n "$PID" ] && kill "$PID" 2>/dev/null
  sleep 1
  setsid .venv/bin/streamlit run app.py \
    --server.headless true --server.port 8501 --server.address 0.0.0.0 \
    > /tmp/streamlit.log 2>&1 < /dev/null &
  sleep 8
}

start_tunnel() {
  setsid cloudflared tunnel --url http://localhost:8501 --no-autoupdate \
    > /tmp/cf-streamlit.log 2>&1 < /dev/null &
  for i in $(seq 1 20); do
    U=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cf-streamlit.log | tail -1)
    [ -n "$U" ] && break
    sleep 1
  done
  [ -n "$U" ] && echo "$U" > /tmp/cf-url.txt
}

while true; do
  curl -fsS -m 5 -o /dev/null http://127.0.0.1:8501/_stcore/health 2>/dev/null || start_streamlit
  pgrep -f "cloudflared tunnel --url http://localhost:8501" >/dev/null 2>&1 || start_tunnel
  sleep 30
done

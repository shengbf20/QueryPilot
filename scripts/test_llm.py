"""验证 DeepSeek API 连通性。"""

from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def main() -> int:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    if not api_key or api_key.startswith("sk-your"):
        print("错误：请在 .env 中设置有效的 DEEPSEEK_API_KEY")
        return 1

    client = OpenAI(api_key=api_key, base_url=base_url)

    print(f"正在调用 {model} @ {base_url} ...")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": "回复 OK 两个字母即可。"},
        ],
        max_tokens=10,
    )

    content = response.choices[0].message.content
    print(f"响应: {content}")
    print(f"Token 用量: {response.usage}")
    print("API 调用成功。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

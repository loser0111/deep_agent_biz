#!/usr/bin/env python3
"""模型接入诊断脚本：一次跑完，定位到底是 base_url、鉴权、格式还是模型名的问题。

用法：
    cd deep-agent
    python scripts/diagnose.py

只用标准库，不需要额外装依赖。

背景（很关键，两种 SDK 的 base_url 约定不一样）：
    OpenAI SDK    —— base_url 【要】包含 /v1，SDK 拼的是 {base_url}/chat/completions
    Anthropic SDK —— base_url 【不要】包含 /v1，SDK 拼的是 {base_url}/v1/messages
所以同一个网关，两个 provider 要填的 base_url 是不同的。
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT = 20


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def mask(secret: str) -> str:
    return f"{secret[:8]}****(len={len(secret)})" if secret else "(未设置)"


def request(method, url, headers, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def brief(body: str, limit: int = 220) -> str:
    text = (body or "").strip().replace("\n", " ")
    return text[:limit] + ("…" if len(text) > limit else "")


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    env = load_env(root / ".env")

    provider = env.get("MODEL_PROVIDER", "openai").strip().lower()
    model = env.get("MODEL_NAME", "").strip()
    is_anthropic = provider in ("anthropic", "claude")

    if is_anthropic:
        api_key = env.get("ANTHROPIC_API_KEY", "").strip()
        base_url = env.get("ANTHROPIC_BASE_URL", "").strip().rstrip("/")
        key_name, url_name = "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"
    else:
        api_key = env.get("OPENAI_API_KEY", "").strip()
        base_url = env.get("OPENAI_BASE_URL", "").strip().rstrip("/")
        key_name, url_name = "OPENAI_API_KEY", "OPENAI_BASE_URL"

    print("=" * 76)
    print("配置读取（.env）")
    print("=" * 76)
    print(f"  MODEL_PROVIDER  = {provider}")
    print(f"  MODEL_NAME      = {model}")
    print(f"  {key_name:<15} = {mask(api_key)}")
    print(f"  {url_name:<15} = {base_url or '(未设置)'}")
    print()

    if not api_key:
        print(f"{key_name} 为空，先填上再跑。")
        return 2
    if not base_url:
        print(f"{url_name} 为空。官方 OpenAI 请删掉这一行；兼容端点请填地址。")
        return 2

    # 候选 API 根：原样、去掉尾部 /v1、补上 /v1
    parent = base_url[:-3].rstrip("/") if base_url.endswith("/v1") else base_url
    candidates = list(dict.fromkeys([base_url, parent, f"{parent}/v1"]))

    openai_hdrs = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    anthropic_hdrs = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Accept": "application/json",
    }
    payload = {"model": model, "max_tokens": 8, "messages": [{"role": "user", "content": "ping"}]}

    print("=" * 76)
    print("逐个候选探测（OpenAI 格式 vs Anthropic 格式）")
    print("=" * 76)

    openai_ok = anthropic_ok = None
    for cand in candidates:
        # --- OpenAI 格式 ---
        st, bd = request("POST", f"{cand}/chat/completions", openai_hdrs, payload)
        mark = "✓" if st == 200 else "✗"
        print(f"  {mark} [{st}] OpenAI    POST {cand}/chat/completions")
        if st != 200:
            print(f"          {brief(bd)}")
        else:
            openai_ok = openai_ok or cand

        # --- Anthropic 格式（SDK 约定：/v1 是路径的一部分）---
        st2, bd2 = request("POST", f"{cand}/v1/messages", anthropic_hdrs, payload)
        mark2 = "✓" if st2 == 200 else "✗"
        print(f"  {mark2} [{st2}] Anthropic POST {cand}/v1/messages")
        if st2 != 200:
            print(f"          {brief(bd2)}")
        else:
            anthropic_ok = anthropic_ok or cand
        print()

    print("=" * 76)
    print("结论")
    print("=" * 76)

    if openai_ok:
        print(f"  ✅ 网关支持 OpenAI 格式。.env 应配成：")
        print(f"        MODEL_PROVIDER=openai_compatible")
        print(f"        OPENAI_BASE_URL={openai_ok}          # 注意：OpenAI 的 base_url 含 /v1")
        print(f"        OPENAI_API_KEY=<你的 key>")
        print(f"        MODEL_NAME={model}")
        return 0

    if anthropic_ok:
        print(f"  ✅ 网关支持 Anthropic 格式。.env 应配成：")
        print(f"        MODEL_PROVIDER=anthropic")
        print(f"        ANTHROPIC_BASE_URL={anthropic_ok}    # 注意：Anthropic 的 base_url 不含 /v1")
        print(f"        ANTHROPIC_API_KEY=<你的 key>")
        print(f"        MODEL_NAME={model}")
        print()
        print("     原理：Anthropic SDK 会自动补 /v1/messages，所以 base_url 填到 /v1 之前；")
        print("           多填一层 /v1 会变成 /v1/v1/messages 而 404。")
        return 0

    print("  ❌ 两种格式都没通。判断线索：")
    print("       401/403 → key 不对或没带上")
    print("       404     → 路径不对（base_url 多填/少填了一层 /v1）")
    print("       400     → 路径和鉴权都对，是模型名不对")
    print("       5xx     → 网关侧问题")
    return 1


if __name__ == "__main__":
    sys.exit(main())

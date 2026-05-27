#!/usr/bin/env python3
"""
skills/embodied-nav/scripts/navigate.py

OpenClaw Skill 导航脚本：
接收 --destination 参数，调用 Flask 后端 /api/navigate，
将结果以 JSON 格式输出给 OpenClaw。
"""

import argparse
import json
import sys
import os
import requests


def main():
    parser = argparse.ArgumentParser(
        description="Embodied Navigation — 调用 Flask 后端控制机器人导航"
    )
    parser.add_argument(
        "--destination",
        required=True,
        choices=["sofa", "bed", "dining_table", "desk", "exit", "front_door"],
        help="导航目标"
    )
    parser.add_argument(
        "--user-input",
        default="",
        help="原始用户输入（用于日志）"
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("FLASK_BASE_URL", "http://127.0.0.1:5001"),
        help="Flask 后端 URL"
    )
    args = parser.parse_args()

    # 打印思考链（给 OpenClaw 看）
    target_labels = {
        "sofa": "沙发",
        "bed": "床边",
        "dining_table": "餐桌",
        "desk": "书桌",
        "exit": "门口",
        "front_door": "门口",
    }
    label = target_labels.get(args.destination, args.destination)

    print(f"🤖 收到导航请求：{label}（{args.destination}）", file=sys.stderr)
    if args.user_input:
        print(f"📝 原始输入：{args.user_input}", file=sys.stderr)
    print(f"🔗 调用 Flask: {args.base_url}/api/navigate", file=sys.stderr)

    try:
        resp = requests.post(
            f"{args.base_url}/api/navigate",
            json={
                "destination": args.destination,
                "user_input": args.user_input
            },
            timeout=60
        )
        resp.raise_for_status()
        result = resp.json()

    except requests.exceptions.ConnectionError:
        error_result = {
            "success": False,
            "code": "SIM_NOT_READY",
            "error": "仿真器未启动，请先运行：\npython server/app.py"
        }
        print(json.dumps(error_result))
        sys.exit(1)

    except requests.exceptions.Timeout:
        error_result = {
            "success": False,
            "code": "TIMEOUT",
            "error": "导航请求超时，请检查仿真器状态"
        }
        print(json.dumps(error_result))
        sys.exit(1)

    except requests.exceptions.HTTPError as e:
        error_result = {
            "success": False,
            "error": f"HTTP {e.response.status_code}: {e.response.text}",
            "code": "HTTP_ERROR"
        }
        print(json.dumps(error_result))
        sys.exit(1)

    except Exception as e:
        error_result = {
            "success": False,
            "error": str(e),
            "code": "UNKNOWN"
        }
        print(json.dumps(error_result))
        sys.exit(1)

    # 输出 JSON 结果（给 OpenClaw 解析）
    print(json.dumps(result))

    # 打印成功日志
    if result.get("success") and result.get("arrived"):
        print(f"✅ 成功到达 {label}！", file=sys.stderr)
    elif result.get("success"):
        print(f"⚠️ 到达但未精确抵达 {label}", file=sys.stderr)
    else:
        print(f"❌ 导航失败: {result.get('error', '未知错误')}", file=sys.stderr)


if __name__ == "__main__":
    main()
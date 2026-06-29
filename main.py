"""Byou 快速启动脚本

使用方式:
    python main.py pipeline --card <名片图片路径> [--audio <录音路径>] [--skip researcher,synthesizer]
    python main.py extract --card <名片图片>
    python main.py research --company <公司名>
    python main.py status
    python main.py serve

详细的 CLI 通过 byou.cli 提供，此文件作为便捷入口。
"""

import sys

if __name__ == "__main__":
    from byou.cli import cli
    sys.exit(cli())

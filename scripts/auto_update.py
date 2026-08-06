#!/usr/bin/env python3
"""
自动更新数据并推送到 GitHub。
由 Kimi Work Automation 定时调用。
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def run(cmd, **kw):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        print(f"ERR: {' '.join(cmd)}\n{r.stderr}", file=sys.stderr)
        return False, r.stderr
    return True, r.stdout

# 1. 更新数据
print("[1/3] 抓取最新 ETF 数据...")
ok, out = run([sys.executable, str(ROOT / "scripts" / "fetch_data.py")], timeout=600)
if not ok:
    print("数据抓取失败，终止。", file=sys.stderr)
    sys.exit(1)

# 2. 检查是否有变更
print("[2/3] 检查是否有数据更新...")
ok, diff = run(["git", "diff", "--quiet", "HEAD"])
if ok:
    print("数据无变化，无需推送。")
    sys.exit(0)

# 3. 提交并推送
print("[3/3] 提交并推送到 GitHub...")
from datetime import datetime
run(["git", "add", "index.html", "data/"])
ok, _ = run(["git", "commit", "-m", f"auto: update data {datetime.now().strftime('%Y-%m-%d')}"])
if not ok:
    print("提交失败", file=sys.stderr)
    sys.exit(1)

ok, out = run(["git", "push", "origin", "main"])
if not ok:
    print(f"推送失败: {out}", file=sys.stderr)
    sys.exit(1)

print("✅ 自动更新完成并已推送到 GitHub。")

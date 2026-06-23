#!/usr/bin/env python3
"""
compare_rng.py — DCRobot RNG 比較腳本

比較三個隨機數來源：
  v1      : /dev/dcrobot_rng    (純 get_random_bytes)
  v2      : /dev/dcrobot_rng_v2 (rdtsc + ktime + jiffies mixing)
  baseline: /dev/urandom        (kernel 標準)

輸出：
  - 熵值（entropy）
  - Chi-square 統計
  - 分布視覺化（scatter plot）
  - 頻率直方圖

需要：pip install matplotlib numpy scipy
執行：sudo python3 compare_rng.py
"""

import struct
import math
import os
import sys

try:
    import numpy as np
    import matplotlib.pyplot as plt
    from scipy import stats as sp_stats
    HAS_PLOT = True
except ImportError:
    HAS_PLOT = False
    print("[warn] matplotlib/numpy/scipy not installed, skipping plots")

SAMPLE_BYTES = 65536   # 64KB per source
SOURCES = [
    ("/dev/dcrobot_rng",    "v1 (get_random_bytes)"),
    ("/dev/dcrobot_rng_v2", "v2 (rdtsc + ktime mixing)"),
    ("/dev/urandom",        "baseline (/dev/urandom)"),
    (None,                   "Python random.randint()"),
]

# ── 熵值計算 ─────────────────────────────────────────────────
def calc_entropy(data: bytes) -> float:
    freq = [0] * 256
    for b in data:
        freq[b] += 1
    n = len(data)
    entropy = 0.0
    for f in freq:
        if f > 0:
            p = f / n
            entropy -= p * math.log2(p)
    return entropy

# ── Chi-square 測試 ──────────────────────────────────────────
def chi_square(data: bytes):
    freq = [0] * 256
    for b in data:
        freq[b] += 1
    expected = len(data) / 256
    chi2 = sum((f - expected) ** 2 / expected for f in freq)
    return chi2

# ── 讀取資料 ─────────────────────────────────────────────────
def read_source(path, n: int) -> bytes:
    # path=None 代表用 Python random.randint()
    if path is None:
        import random, struct
        data = b""
        while len(data) < n:
            val = random.randint(0, 2**32 - 1)
            data += struct.pack("<I", val)
        return data[:n]
    data = b""
    try:
        with open(path, "rb") as f:
            while len(data) < n:
                chunk = f.read(min(4096, n - len(data)))
                if not chunk:
                    break
                data += chunk
    except PermissionError:
        print(f"[error] {path}: permission denied, try sudo")
        sys.exit(1)
    except FileNotFoundError:
        print(f"[error] {path}: not found (module loaded?)")
        sys.exit(1)
    return data

# ── 主程式 ───────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("DCRobot RNG 比較測試")
    print(f"樣本大小: {SAMPLE_BYTES // 1024} KB per source")
    print("=" * 60)

    results = []
    all_data = []

    for path, label in SOURCES:
        print(f"\n[{label}]")
        data = read_source(path, SAMPLE_BYTES)
        entropy = calc_entropy(data)
        chi2    = chi_square(data)

        # 轉成 uint32 序列
        n32 = len(data) // 4
        nums = list(struct.unpack(f"<{n32}I", data[:n32 * 4]))

        print(f"  熵值        : {entropy:.6f} bits/byte  (理想值: 8.000000)")
        print(f"  Chi-square  : {chi2:.2f}  (df=255, 理想範圍: 200~310)")
        print(f"  最小值      : {min(nums)}")
        print(f"  最大值      : {max(nums)}")
        print(f"  平均值      : {sum(nums)//len(nums)}")

        results.append((label, entropy, chi2, nums))
        all_data.append(data)

    # ── 總結 ──────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("總結比較")
    print("=" * 60)
    print(f"{'來源':<30} {'熵值':>12} {'Chi²':>10}")
    print("-" * 55)
    for label, entropy, chi2, _ in results:
        bar = "★" if entropy > 7.999 else ""
        print(f"{label:<30} {entropy:>12.6f} {chi2:>10.2f} {bar}")

    # ── 視覺化 ────────────────────────────────────────────────
    if not HAS_PLOT:
        return

    fig, axes = plt.subplots(2, 4, figsize=(20, 8))
    fig.suptitle("DCRobot RNG 比較：v1 vs v2 vs urandom", fontsize=14, fontweight="bold")

    colors = ["#44C9E0", "#3DCEA9", "#F4C430", "#9B6DFF"]

    for i, (label, entropy, chi2, nums) in enumerate(results):
        # 上排：scatter plot（相鄰兩個數字的分布）
        ax_scatter = axes[0][i]
        xs = nums[::2][:512]
        ys = nums[1::2][:512]
        ax_scatter.scatter(xs, ys, s=2, alpha=0.5, color=colors[i])
        ax_scatter.set_title(f"{label}\nentropy={entropy:.4f}", fontsize=9)
        ax_scatter.set_xlabel("x[n]")
        ax_scatter.set_ylabel("x[n+1]")

        # 下排：byte 頻率直方圖
        ax_hist = axes[1][i]
        freq = [0] * 256
        for b in all_data[i]:
            freq[b] += 1
        ax_hist.bar(range(256), freq, color=colors[i], alpha=0.7, width=1)
        ax_hist.axhline(y=SAMPLE_BYTES / 256, color="red",
                        linestyle="--", linewidth=1, label="理想均勻值")
        ax_hist.set_xlabel("Byte 值 (0-255)")
        ax_hist.set_ylabel("頻率")
        ax_hist.legend(fontsize=7)

    plt.tight_layout()
    out = "rng_comparison.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"\n[plot] 儲存至 {out}")
    plt.show()

if __name__ == "__main__":
    main()
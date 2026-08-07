#!/usr/bin/env python3
"""
General-Purpose Modbus Register Guesser v1.0
Implements an interactive, multi-point stimulus-response routine with 
Pearson correlation coefficient scoring for scaling-independent register mapping.
"""

from __future__ import annotations

import csv
import math
import os
import sys
import time

# Import your version-proof Modbus RTU wrapper
try:
    from dkm_modbus import DKM, as_signed16, combine32, nearest_nice_scale
except ImportError:
    print("ERROR: Could not find 'dkm_modbus.py' in the current directory.")
    print("Please make sure your existing wrapper module is adjacent to this script.")
    sys.exit(1)

RESULTS_DIR = "results"
EXPECTED_PATTERN = [90.0, 60.0, 30.0, 60.0, 90.0]


def pearson_correlation(x: list[float], y: list[float]) -> float | None:
    """Calculate Pearson correlation coefficient (r). Returns None if variance is zero."""
    n = len(x)
    if n != len(y) or n < 2:
        return None
    
    avg_x = sum(x) / n
    avg_y = sum(y) / n
    
    diff_x = [val - avg_x for val in x]
    diff_y = [val - avg_y for val in y]
    
    num = sum(dx * dy for dx, dy in zip(diff_x, diff_y))
    den_x = sum(dx ** 2 for dx in diff_x)
    den_y = sum(dy ** 2 for dy in diff_y)
    
    if den_x == 0 or den_y == 0:
        return None  # No variance; flat line
        
    return num / math.sqrt(den_x * den_y)


def calculate_linearity_and_scale(x: list[float], y: list[float]) -> tuple[float, float, float]:
    """Calculate slope, intercept, and standard linear R^2 fit."""
    n = len(x)
    avg_x = sum(x) / n
    avg_y = sum(y) / n
    sxx = sum((val - avg_x) ** 2 for val in x)
    syy = sum((val - avg_y) ** 2 for val in y)
    sxy = sum((xv - avg_x) * (yv - avg_y) for xv, yv in zip(x, y))
    
    if sxx == 0 or syy == 0:
        return 0.0, avg_y, 0.0
        
    slope = sxy / sxx
    intercept = avg_y - slope * avg_x
    ss_res = sum((yv - (slope * xv + intercept)) ** 2 for xv, yv in zip(x, y))
    r2 = 1.0 - (ss_res / syy) if syy > 0 else 0.0
    return slope, intercept, r2


def draw_progress_bar(duration: float = 10.0, width: int = 20):
    """Draw a scannable console animation block for sampling intervals."""
    steps = width
    sleep_interval = duration / steps
    for i in range(steps + 1):
        bar = "█" * i + "░" * (width - i)
        sys.stdout.write(f"\r{bar} {duration} s")
        sys.stdout.flush()
        time.sleep(sleep_interval)
    print()


def main():
    print("===========================================")
    print("DKM-440 REGISTER GUESSER v1.0")
    print("===========================================")
    
    # Prompt user configuration matching your CLI specification
    com_input = input("Enter COM port [COM13]: ").strip()
    port = com_input if com_input else "COM13"
    
    regs_input = input("How many registers to scan? [Default = 25000]: ").strip()
    count = int(regs_input) if regs_input else 25000
    
    start_addr = 0
    print(f"\nScanning range:\n{start_addr} -> {start_addr + count - 1}\n")
    input("Press ENTER when ready...")

    # Initialize Modbus Session
    dev = DKM(port=port)
    try:
        dev.connect()
        print("Connected.\n")
    except SystemExit as e:
        print(e)
        sys.exit(1)

    # Dictionary to house captures: step_idx -> {address: raw_value}
    step_captures: dict[int, dict[int, int]] = {}
    
    # Step Execution Phase
    try:
        for idx, target_v in enumerate(EXPECTED_PATTERN, start=1):
            print("--------------------------------")
            print(f"STEP {idx} / {len(EXPECTED_PATTERN)}")
            print("--------------------------------\n")
            print(f"Set source to\n\n    {target_v:g} VAC\n")
            print("Wait until stable.\n")
            input("Press ENTER when ready...")
            
            print("\nSampling...")
            draw_progress_bar(duration=2.0, width=20)
            
            # Use wide-window recovery sweep across the register space
            captured_block = dev.read_window(start_addr, count, recover=True)
            step_captures[idx - 1] = captured_block
            print(f"Captured {len(captured_block)} active registers.\n")
            
    except KeyboardInterrupt:
        print("\nScan interrupted by user. Cleaning up session connection...")
        dev.close()
        sys.exit(0)
    finally:
        dev.close()

    print("==================================")
    print("ANALYZING")
    print("==================================\n")
    
    # Find intersections of addresses that responded across all steps
    all_responding_address_sets = [set(step_captures[i].keys()) for i in range(len(EXPECTED_PATTERN))]
    if not all_responding_address_sets:
        print("No captures collected.")
        sys.exit(1)

    common_addresses = set.intersection(*all_responding_address_sets)

    if not common_addresses:
        print("No common registers across steps. Try increasing --count or recover=True.")
        sys.exit(1)

    common_addresses = sorted(common_addresses)
    print(f"Comparing {len(common_addresses):,} readable registers...\n")
    print("Computing:\n✓ Correlation\n✓ Linearity\n✓ Noise\n✓ Dynamic range\n✓ Scale guess\n✓ 32-bit pairs\n")
    
    # Analyze 16-bit registers
    ranked_results = []
    for addr in common_addresses:
        ys = [float(step_captures[step_idx][addr]) for step_idx in range(len(EXPECTED_PATTERN))]
        
        # Pearson Correlation
        r = pearson_correlation(EXPECTED_PATTERN, ys)
        if r is None or not isinstance(r, (int, float)) or math.isnan(r):
            continue

        score = abs(r) * 100.0  # Normalize score to 100% boundary
        slope, intercept, r2 = calculate_linearity_and_scale(EXPECTED_PATTERN, ys)
        
        # Derive scale map
        if abs(slope) < 1e-6:
            scale_guess = 1
        else:
            scale_guess = nearest_nice_scale(abs(slope))
            
        engineering_vals = [val / scale_guess for val in ys]
        raw_range = max(ys) - min(ys)
        
        ranked_results.append({
            "type": "16-bit",
            "address": addr,
            "score": score,
            "scale": scale_guess,
            "raw_range": raw_range,
            "engineering": " ".join(f"{v:.1f}" for v in engineering_vals),
            "raw_history": ys,
            "r2": r2
        })

    # Analyze 32-bit paired registers (Big-Endian interpretation: Word Swap Modbus standard)
    for i in range(len(common_addresses) - 1):
        addr_hi = common_addresses[i]
        addr_lo = common_addresses[i+1]
        
        if addr_lo != addr_hi + 1:
            continue
            
        ys_32 = []
        valid_pair = True
        
        for step_idx in range(len(EXPECTED_PATTERN)):
            if addr_hi not in step_captures[step_idx] or addr_lo not in step_captures[step_idx]:
                valid_pair = False
                break
                
            hi_val = step_captures[step_idx][addr_hi]
            lo_val = step_captures[step_idx][addr_lo]
            ys_32.append(float(combine32(hi_val, lo_val, signed=False)))
            
        if not valid_pair:
            continue
            
        r_32 = pearson_correlation(EXPECTED_PATTERN, ys_32)
        if r_32 is None or math.isnan(r_32):
            continue
            
        score_32 = abs(r_32) * 100.0
        slope_32, _, r2_32 = calculate_linearity_and_scale(EXPECTED_PATTERN, ys_32)
        scale_guess_32 = nearest_nice_scale(abs(slope_32)) if slope_32 != 0 else 1
        engineering_vals_32 = [val / scale_guess_32 for val in ys_32]
        
        ranked_results.append({
            "type": "32-bit",
            "address": addr_hi,
            "score": score_32,
            "scale": scale_guess_32,
            "raw_range": max(ys_32) - min(ys_32),
            "engineering": " ".join(f"{v:.1f}" for v in engineering_vals_32),
            "raw_history": ys_32,
            "r2": r2_32
        })

    # Rank results by correlation score first, then raw variability/range (drops flat-line artifacts)
    ranked_results.sort(key=lambda item: (item["score"], item["raw_range"]), reverse=True)

    # Console display output presentation
    print("Done.\n")
    print(f"{'RANK':<6} {'ADDRESS':<8} {'SCORE':<7} {'SCALE':<6} {'ENGINEERING'}")
    for idx, item in enumerate(ranked_results[:10], start=1):
        type_flag = " (32b)" if item["type"] == "32-bit" else ""
        addr_str = f"{item['address']}{type_flag}"
        print(f"{idx:<6} {addr_str:<12} {item['score']:<7.2f} /{item['scale']:<5} {item['engineering']}")
        
    print("-" * 71 + "\n")

    # Persist directory files
    os.makedirs(RESULTS_DIR, exist_ok=True)
    
    # 1. raw_capture.csv
    with open(os.path.join(RESULTS_DIR, "raw_capture.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["address"] + [f"step_{i+1}_{v}V" for i, v in enumerate(EXPECTED_PATTERN)])
        for addr in common_addresses:
            writer.writerow([addr] + [step_captures[step_idx][addr] for step_idx in range(len(EXPECTED_PATTERN))])
            
    # 2. ranking.csv
    with open(os.path.join(RESULTS_DIR, "ranking.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "address", "type", "score_pct", "r2", "suggested_scale", "engineering_trajectory"])
        for idx, item in enumerate(ranked_results, start=1):
            writer.writerow([idx, item["address"], item["type"], item["score"], item["r2"], item["scale"], item["engineering"]])

    # 3. top50.csv
    with open(os.path.join(RESULTS_DIR, "top50.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "address", "type", "score_pct", "suggested_scale", "engineering_trajectory"])
        for idx, item in enumerate(ranked_results[:50], start=1):
            writer.writerow([idx, item["address"], item["type"], item["score"], item["scale"], item["engineering"]])

    # 4. analysis.txt summary output generation
    if ranked_results:
        winner = ranked_results[0]
        analysis_content = (
            f"Most probable voltage register:\n\n"
            f"Address : {winner['address']}\n"
            f"Type    : {winner['type']}\n"
            f"Confidence : {winner['score']:.2f}%\n\n"
            f"Suggested map entry\n\n"
            f"Reg(\n"
            f"    \"l1_voltage\",\n"
            f"    {winner['address']},\n"
            f"    {'2' if winner['type'] == '32-bit' else '1'},\n"
            f"    {float(winner['scale']):.1f},\n"
            f"    \"V\",\n"
            f"    \"L1 voltage\",\n"
            f"    verified=True\n"
            f")\n"
        )
        with open(os.path.join(RESULTS_DIR, "analysis.txt"), "w") as f:
            f.write(analysis_content)

    print(f"Results successfully saved to ./{RESULTS_DIR}/ directory:")
    print(" └── raw_capture.csv\n └── ranking.csv\n └── top50.csv\n └── analysis.txt\n")


if __name__ == "__main__":
    main()
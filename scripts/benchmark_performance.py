#!/usr/bin/env python3
"""Runtime inference performance and resource utilization benchmarking.

Measures:
- Model artifact load latency
- Memory usage (RSS and tracemalloc peaks)
- Single-message prediction latency distribution (p50, p90, p95, p99, mean)
- Batch prediction throughput across varying batch sizes (1, 5, 10, 25, 50)
- Exports message-free performance JSON records to benchmarks/
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import sys
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.predict import analyze_batch, analyze_message, load_model  # noqa: E402

SAMPLE_MESSAGES = [
    "GCash: You have received PHP 1,500.00 from Maria Cruz. Ref: 102938475. Balance: PHP 4,250.00.",
    "BDO Alert: We detected an unauthorized login. Verify your identity at https://bdo-verify.example.com immediately.",
    "Good morning ma'am! Regarding po sa meeting natin mamaya, what time po kayo available?",
    "Congratulations! You've been chosen for the PCSO 4D jackpot prize of ₱750,000! Text CLAIM to 09171234567.",
    "Your parcel #JT8492048 is out for delivery today by J&T Express. Rider: Kuya Jun 09181234567.",
    "Final reminder: Your mobile load will expire in 2 hours. Dial *143# to register to GoEXTRA today.",
    "URGENT: BPI account suspended due to suspicious activity. Log in at bit.ly/bpi-security to restore access.",
    "Salamat sa pasalubong kahapon, nagustuhan nila mama at papa!",
]


def _get_rss_mb() -> float:
    """Return resident memory usage in megabytes."""
    rusage = resource.getrusage(resource.RUSAGE_SELF)
    # macOS reports in bytes, Linux in kilobytes
    if platform.system() == "Darwin":
        return rusage.ru_maxrss / (1024 * 1024)
    return rusage.ru_maxrss / 1024


def run_benchmark(
    model_path: Path,
    output_dir: Path = ROOT / "benchmarks",
    iterations: int = 150,
) -> dict[str, Any]:
    """Execute model latency, memory, and throughput benchmarks."""
    output_dir.mkdir(parents=True, exist_ok=True)

    tracemalloc.start()
    initial_rss = _get_rss_mb()

    # 1. Model Loading Benchmark
    load_start = time.perf_counter()
    bundle = load_model(model_path)
    load_duration_ms = (time.perf_counter() - load_start) * 1000.0
    post_load_rss = _get_rss_mb()

    # 2. Warm-up
    for msg in SAMPLE_MESSAGES:
        analyze_message(msg, model=bundle)

    # 3. Single Prediction Latency
    latencies_ms: list[float] = []
    num_samples = len(SAMPLE_MESSAGES)

    for i in range(iterations):
        msg = SAMPLE_MESSAGES[i % num_samples]
        t0 = time.perf_counter()
        analyze_message(msg, model=bundle)
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)

    lat_arr = np.array(latencies_ms)
    percentiles = np.percentile(lat_arr, [50, 90, 95, 99])

    # 4. Batch Throughput
    batch_sizes = [1, 5, 10, 25, 50]
    batch_results: dict[str, Any] = {}

    for size in batch_sizes:
        batch = [SAMPLE_MESSAGES[j % num_samples] for j in range(size)]
        # Run 10 repeats per batch size
        batch_times: list[float] = []
        for _ in range(10):
            t0 = time.perf_counter()
            analyze_batch(batch, model=bundle)
            batch_times.append(time.perf_counter() - t0)

        mean_batch_time_sec = float(np.mean(batch_times))
        msgs_per_sec = size / mean_batch_time_sec if mean_batch_time_sec > 0 else 0.0
        batch_results[f"batch_{size}"] = {
            "batch_size": size,
            "mean_batch_time_ms": round(mean_batch_time_sec * 1000.0, 3),
            "per_item_time_ms": round((mean_batch_time_sec * 1000.0) / size, 3),
            "throughput_msgs_per_sec": round(msgs_per_sec, 1),
        }

    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    final_rss = _get_rss_mb()

    results: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "model_version": getattr(bundle, "model_version", "unknown"),
        "model_path": str(model_path),
        "system": {
            "os": platform.system(),
            "os_release": platform.release(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
        },
        "model_load": {
            "load_time_ms": round(load_duration_ms, 2),
            "memory_delta_mb": round(post_load_rss - initial_rss, 2),
        },
        "single_prediction_latency_ms": {
            "iterations": iterations,
            "mean": round(float(np.mean(lat_arr)), 3),
            "std": round(float(np.std(lat_arr)), 3),
            "min": round(float(np.min(lat_arr)), 3),
            "max": round(float(np.max(lat_arr)), 3),
            "p50": round(float(percentiles[0]), 3),
            "p90": round(float(percentiles[1]), 3),
            "p95": round(float(percentiles[2]), 3),
            "p99": round(float(percentiles[3]), 3),
        },
        "batch_throughput": batch_results,
        "memory_profile_mb": {
            "initial_rss": round(initial_rss, 2),
            "final_rss": round(final_rss, 2),
            "tracemalloc_peak": round(peak_mem / (1024 * 1024), 2),
        },
    }

    timestamp_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out_file = output_dir / f"performance_{timestamp_str}.json"
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


def print_summary(res: dict[str, Any]) -> None:
    """Print formatted performance summary table."""
    print("\n" + "=" * 60)
    print(" SMS Spam Detector — Runtime Performance Benchmark")
    print("=" * 60)
    print(f"Model Version: {res['model_version']}")
    print(f"Platform:      {res['system']['os']} {res['system']['machine']} (Python {res['system']['python_version']})")
    print(f"Model Load:    {res['model_load']['load_time_ms']:.2f} ms")
    print("-" * 60)
    print("Single Prediction Latency (ms):")
    lat = res["single_prediction_latency_ms"]
    print(f"  p50:  {lat['p50']:>6.2f} ms  |  p90: {lat['p90']:>6.2f} ms")
    print(f"  p95:  {lat['p95']:>6.2f} ms  |  p99: {lat['p99']:>6.2f} ms")
    print(f"  Mean: {lat['mean']:>6.2f} ms  |  Min: {lat['min']:>6.2f} ms  |  Max: {lat['max']:>6.2f} ms")
    print("-" * 60)
    print("Batch Throughput:")
    print("  Batch Size | Time / Batch (ms) | Time / Item (ms) | Throughput (msgs/sec)")
    for _key, data in res["batch_throughput"].items():
        print(
            f"  {data['batch_size']:>10d} | {data['mean_batch_time_ms']:>17.2f} | "
            f"{data['per_item_time_ms']:>16.2f} | {data['throughput_msgs_per_sec']:>18.1f}"
        )
    print("-" * 60)
    mem = res["memory_profile_mb"]
    print(
        f"Memory: Initial RSS: {mem['initial_rss']:.1f} MB | Final RSS: {mem['final_rss']:.1f} MB | Peak Allocated: {mem['tracemalloc_peak']:.2f} MB"
    )
    print("=" * 60 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SMS spam detector inference performance benchmark.")
    parser.add_argument(
        "--model",
        type=Path,
        default=ROOT / "models" / "sms_spam_model.joblib",
        help="Path to trained model bundle (.joblib).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "benchmarks",
        help="Directory to save benchmark JSON results.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=100,
        help="Number of single-prediction iterations to benchmark (default: 100).",
    )
    args = parser.parse_args()

    model_path = args.model
    if not model_path.exists():
        # Fallback check for alternate locations or train a fast demo model
        print(f"Model artifact not found at {model_path}. Training a temporary benchmark model...", file=sys.stderr)
        from src.train import train

        supplements = [
            ROOT / "data" / "raw" / "ph_supplement.csv",
            ROOT / "data" / "raw" / "ph_supplement_2.csv",
        ]
        existing_supplements = [s for s in supplements if s.exists()]
        if not existing_supplements:
            print("Error: Training data fixtures not found.", file=sys.stderr)
            return 1
        train(
            data_path=existing_supplements[0],
            supplement_path=existing_supplements[1:],
            holdout_path=None,
            model_path=model_path,
            val_size=0.2,
            test_size=0.2,
            verbose=False,
        )

    res = run_benchmark(model_path=model_path, output_dir=args.output_dir, iterations=args.iterations)
    print_summary(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
scripts/compare_algorithms.py — Head-to-Head Comparative Benchmark
Google SigLIP (with Softmax + EMA) vs Original OpenAI CLIP (raw cosine)

Runs 5 benchmark targets under identical spawn positions and orientations.
"""

import sys
import time
import requests
import json

FLASK_BASE = "http://127.0.0.1:5001"
BENCHMARKS = {
    "sofa": "sofa",
    "television": "television",
    "dining_table": "dining_table",
    "chair": "chair",
    "exit": "exit",
}

def wait_ready(timeout: int = 20) -> bool:
    """Wait for Flask server and CLIP initialization."""
    for i in range(timeout):
        try:
            r = requests.get(f"{FLASK_BASE}/api/health", timeout=2)
            if r.status_code == 200:
                data = r.json()
                if data.get("clip_ready"):
                    return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(1)
    return False

def configure_backend(model_type: str, arrive_threshold: float):
    """Update active backend configuration."""
    r = requests.post(
        f"{FLASK_BASE}/api/config",
        json={"model_type": model_type, "arrive_threshold": arrive_threshold},
        timeout=5
    )
    assert r.status_code == 200, f"Failed to configure backend: {r.text}"
    return r.json()

def teleport_agent(position, rotation):
    """Teleport agent to a specific spawn point."""
    r = requests.post(
        f"{FLASK_BASE}/api/teleport",
        json={"position": position, "rotation": rotation},
        timeout=5
    )
    assert r.status_code == 200, f"Failed to teleport: {r.text}"
    return r.json()

def reset_agent():
    """Trigger reset on the server to get a random navigable spawn point."""
    r = requests.post(f"{FLASK_BASE}/api/reset", timeout=10)
    assert r.status_code == 200, f"Failed to reset: {r.text}"
    data = r.json()
    return data["position"]

def run_navigation(target: str):
    """Trigger blocking navigation for a target."""
    r = requests.post(
        f"{FLASK_BASE}/api/navigate",
        json={"destination": target, "user_input": f"帮我找到{target}"},
        timeout=350 # Bounded long-range time
    )
    assert r.status_code == 200, f"Navigation failed to respond: {r.text}"
    return r.json()

def main():
    print("=" * 70)
    print("Embodied Navigation — Dynamic Algorithmic Benchmark")
    print("Google SigLIP vs Original OpenAI CLIP")
    print("=" * 70)
    
    print("\n[1/4] Waiting for backend and models to be ready...")
    if not wait_ready():
        print("❌ Flask server or visual models are not ready. Start server/app.py first!")
        sys.exit(1)
    print("✅ Backend and both models are preloaded and ready.")
    
    results = {
        "siglip": {},
        "clip": {},
    }
    
    spawn_points = {}
    
    print("\n[2/4] Initializing identical spawn points for fairness...")
    # Gather distinct spawn points for each of the 5 targets by resetting
    for target in BENCHMARKS:
        pos = reset_agent()
        # Set a default orientation
        rot = [1.0, 0.0, 0.0, 0.0]
        spawn_points[target] = {"pos": pos, "rot": rot}
        print(f"  📍 Start position for {target.upper()}: {pos}")
        time.sleep(1.0)
        
    # --- PHASE 1: Original CLIP ---
    print("\n[3/4] Running Phase 1: Original OpenAI CLIP (No Contrastive Softmax, No EMA)")
    print("-" * 50)
    for target, eng_name in BENCHMARKS.items():
        print(f"\n🚀 Target: {target.upper()} | Model: original CLIP")
        configure_backend(model_type="clip", arrive_threshold=27.0)
        
        # Teleport to the identical spawn point
        sp = spawn_points[target]
        teleport_agent(sp["pos"], sp["rot"])
        time.sleep(0.5)
        
        # Run navigation
        t_start = time.time()
        res = run_navigation(eng_name)
        duration = time.time() - t_start
        
        results["clip"][target] = {
            "arrived": res.get("arrived", False),
            "steps": res.get("steps", 0),
            "highest_conf": res.get("highest_conf", 0.0),
            "time_s": duration
        }
        print(f"   Success: {res.get('arrived')}, Steps: {res.get('steps')}, Peak Conf: {res.get('highest_conf'):.2f}, Time: {duration:.1f}s")
        time.sleep(1.5)
        
    # --- PHASE 2: Optimized SigLIP ---
    print("\n[4/4] Running Phase 2: Google SigLIP (With Softmax + EMA, ARRIVE=24.0)")
    print("-" * 50)
    for target, eng_name in BENCHMARKS.items():
        print(f"\n🚀 Target: {target.upper()} | Model: Google SigLIP")
        configure_backend(model_type="siglip", arrive_threshold=24.0)
        
        # Teleport to the identical spawn point
        sp = spawn_points[target]
        teleport_agent(sp["pos"], sp["rot"])
        time.sleep(0.5)
        
        # Run navigation
        t_start = time.time()
        res = run_navigation(eng_name)
        duration = time.time() - t_start
        
        results["siglip"][target] = {
            "arrived": res.get("arrived", False),
            "steps": res.get("steps", 0),
            "highest_conf": res.get("highest_conf", 0.0),
            "time_s": duration
        }
        print(f"   Success: {res.get('arrived')}, Steps: {res.get('steps')}, Peak Conf: {res.get('highest_conf'):.2f}, Time: {duration:.1f}s")
        time.sleep(1.5)
        
    # --- PRINT COMPARISON TABLE ---
    print("\n" + "=" * 80)
    print(f"{'Target':<14} | {'CLIP Success':<12} {'CLIP Steps':<10} {'CLIP Conf':<10} | {'SigLIP Success':<14} {'SigLIP Steps':<12} {'SigLIP Conf':<10}")
    print("-" * 80)
    
    clip_success_count = 0
    siglip_success_count = 0
    clip_total_steps = 0
    siglip_total_steps = 0
    
    for target in BENCHMARKS:
        c = results["clip"][target]
        s = results["siglip"][target]
        
        c_ok = "✅ YES" if c["arrived"] else "❌ NO"
        s_ok = "✅ YES" if s["arrived"] else "❌ NO"
        
        print(f"{target:<14} | {c_ok:<12} {c['steps']:<10} {c['highest_conf']:<10.2f} | {s_ok:<14} {s['steps']:<12} {s['highest_conf']:<10.2f}")
        
        if c["arrived"]:
            clip_success_count += 1
            clip_total_steps += c["steps"]
        if s["arrived"]:
            siglip_success_count += 1
            siglip_total_steps += s["steps"]
            
    print("=" * 80)
    
    clip_avg_steps = clip_total_steps / clip_success_count if clip_success_count > 0 else 0
    siglip_avg_steps = siglip_total_steps / siglip_success_count if siglip_success_count > 0 else 0
    
    print(f"CLIP Success Rate  : {clip_success_count}/5 ({100*clip_success_count/5:.0f}%) | Avg Steps (Successful): {clip_avg_steps:.1f}")
    print(f"SigLIP Success Rate: {siglip_success_count}/5 ({100*siglip_success_count/5:.0f}%) | Avg Steps (Successful): {siglip_avg_steps:.1f}")
    print("=" * 80)
    
    # Save the output to a JSON file for automatic verification and readme updates
    with open("data/benchmark_results.json", "w") as f:
        json.dump(results, f, indent=4)
    print("Benchmark results saved to data/benchmark_results.json")

if __name__ == "__main__":
    main()

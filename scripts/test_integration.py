#!/usr/bin/env python3
"""
scripts/test_integration.py — End-to-End Integration Tests

Tests all 5 navigation targets by calling the Flask API directly.
Requires: server/app.py running + Replica data downloaded.
"""

import sys
import time
import requests

FLASK_BASE = "http://127.0.0.1:5001"

TARGETS = ["sofa", "bed", "dining_table", "desk", "exit"]


def wait_ready(timeout: int = 10) -> bool:
    """Wait for Flask server to be ready."""
    for i in range(timeout):
        try:
            r = requests.get(f"{FLASK_BASE}/api/health", timeout=2)
            if r.status_code == 200:
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(1)
    return False


def test_status():
    """Test /api/status endpoint."""
    r = requests.get(f"{FLASK_BASE}/api/status")
    assert r.status_code == 200, f"status failed: {r.status_code}"
    data = r.json()
    print(f"  ✅ Status: simulator={data['simulator']}, pos={data['agent_position']}")
    return data


def test_health():
    """Test /api/health endpoint."""
    r = requests.get(f"{FLASK_BASE}/api/health")
    assert r.status_code == 200
    print("  ✅ Health check OK")


def test_navigate(target: str) -> bool:
    """Test navigation to a specific target."""
    print(f"\n  🚶 Testing navigation to: {target}")
    r = requests.post(
        f"{FLASK_BASE}/api/navigate",
        json={"destination": target, "user_input": f"请到{target}旁边"},
        timeout=300
    )
    data = r.json()
    print(f"     success={data['success']}, arrived={data.get('arrived', False)}")
    if data.get("target_position"):
        print(f"     target: {data['target_position']}")
    if data.get("arrived_position"):
        print(f"     arrived: {data['arrived_position']}")
    if data.get("path_length"):
        print(f"     path_length: {data['path_length']:.2f}m")
    if not data["success"]:
        print(f"     ❌ ERROR: {data.get('error', 'unknown')}")
    return data.get("arrived", False)


def test_reset():
    """Test /api/reset endpoint."""
    r = requests.post(f"{FLASK_BASE}/api/reset")
    assert r.status_code == 200
    data = r.json()
    assert data["success"], f"reset failed: {data}"
    print("  ✅ Reset OK")


def test_scan(target: str):
    """Test CLIP scan for a target."""
    print(f"\n  👁️ Testing CLIP scan: {target}")
    r = requests.post(
        f"{FLASK_BASE}/api/scan",
        json={"target": target},
        timeout=30
    )
    data = r.json()
    if not data["success"]:
        print(f"     ⚠️  Scan failed: {data.get('error', 'unknown')}")
        return False
    print(f"     best_direction={data['best_direction']}, confidence={data['confidence']:.3f}")
    print(f"     view_scores={[f'{s:.3f}' for s in data['view_scores']]}")
    print(f"     inference_time={data['inference_time_ms']:.0f}ms")
    return True


def main():
    print("=" * 60)
    print("Embodied Navigation — Integration Tests")
    print("=" * 60)

    print("\n[1/5] Waiting for Flask server...")
    if not wait_ready(timeout=15):
        print("❌ Flask server not responding. Start with: python server/app.py")
        sys.exit(1)
    print("✅ Flask server is ready.")

    print("\n[2/5] Testing health & status endpoints...")
    test_health()
    test_status()

    print("\n[3/5] Testing CLIP scans...")
    scan_results = {}
    for target in TARGETS:
        scan_results[target] = test_scan(target)

    print("\n[4/5] Testing navigation...")
    nav_results = {}
    for target in TARGETS:
        # Reset before each navigation test
        test_reset()
        time.sleep(0.5)
        nav_results[target] = test_navigate(target)
        time.sleep(0.5)

    print("\n[5/5] Summary")
    print("-" * 40)
    print(f"{'Target':<15} {'Scan':<6} {'Navigate':<10}")
    print("-" * 40)
    for target in TARGETS:
        scan_ok = "✅" if scan_results.get(target) else "⚠️"
        nav_ok = "✅" if nav_results.get(target) else "❌"
        print(f"{target:<15} {scan_ok:<6} {nav_ok:<10}")

    passed = sum(1 for v in nav_results.values() if v)
    total = len(TARGETS)
    print(f"\nNavigation success rate: {passed}/{total} ({100*passed//total}%)")

    if passed == total:
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print(f"\n⚠️  {total - passed} tests failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
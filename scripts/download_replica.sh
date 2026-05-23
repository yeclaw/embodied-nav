# Download Replica dataset for embodied-nav
# Usage: bash scripts/download_replica.sh

set -e

DATA_DIR="${HABITAT_DATA_PATH:-$HOME/.habitat-data}"
SCENE="apartment_0"

echo "=== Downloading Replica scene: $SCENE ==="
echo "Data directory: $DATA_DIR"
mkdir -p "$DATA_DIR"

# Method 1: Habitat official download script (preferred)
if command -v python3 &> /dev/null; then
    echo "Attempting habitat_sim.datasets_download..."
    python3 -m habitat_sim.utils.datasets_download \
        --uids habitat_test_scenes \
        --data-path "$DATA_DIR" \
        --no-problems 2>/dev/null || true
fi

# Method 2: Direct download via wget
REPLICA_URL="https://github.com/facebookresearch/Replica-Dataset/raw/main/data/apartment_0.zip"
DEST_ZIP="$DATA_DIR/apartment_0.zip"
DEST_DIR="$DATA_DIR/Replica/apartment_0"

if [ -d "$DEST_DIR" ]; then
    echo "✅ Replica apartment_0 already exists at $DEST_DIR"
else
    echo "📦 Downloading Replica apartment_0 (~500MB)..."
    mkdir -p "$DATA_DIR/Replica"

    if command -v wget &> /dev/null; then
        wget -O "$DEST_ZIP" "$REPLICA_URL" || curl -L -o "$DEST_ZIP" "$REPLICA_URL"
    else
        curl -L -o "$DEST_ZIP" "$REPLICA_URL"
    fi

    echo "📦 Extracting..."
    if command -v unzip &> /dev/null; then
        unzip -q "$DEST_ZIP" -d "$DATA_DIR/Replica/"
    fi

    rm -f "$DEST_ZIP"
    echo "✅ Downloaded and extracted to $DEST_DIR"
fi

echo ""
echo "Scene files:"
ls "$DEST_DIR/" 2>/dev/null || echo "  (files not found)"
echo ""
echo "=== Download Complete ==="
echo "HABITAT_DATA_PATH=$DATA_DIR"
echo "Run: python server/app.py"
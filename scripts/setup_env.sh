#!/bin/bash
# setup_env.sh — Environment setup for embodied-nav
# Usage: bash scripts/setup_env.sh

set -e

echo "=== Embodied Navigation: Environment Setup ==="

# 1. Check for conda
if ! command -v conda &> /dev/null; then
    echo "❌ Conda not found. Installing miniconda3 (ARM64)..."
    curl -O https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh
    bash Miniconda3-latest-MacOSX-arm64.sh -b -p ~/miniconda3
    rm Miniconda3-latest-MacOSX-arm64.sh
    export PATH="$HOME/miniconda3/bin:$PATH"
    ~/miniconda3/bin/conda init zsh
    echo "✅ Miniconda3 installed. Source your shell or restart terminal."
    exit 0
fi

echo "✅ Conda found"

# 2. Create environment
echo "📦 Creating conda environment 'embodied-nav'..."
conda create -y -n embodied-nav python=3.12 cmake=3.27 -c conda-forge
conda activate embodied-nav

# 3. Install habitat-sim
echo "🤖 Installing habitat-sim..."
conda install -y habitat-sim withbullet -c conda-forge -c aihabitat

# 4. Install Python deps
echo "🐍 Installing Python packages..."
pip install --upgrade pip
pip install torch transformers pillow flask opencv-python requests gunicorn

# 5. Verify
echo "🔍 Verifying installation..."
python -c "import habitat_sim; print(f'habitat-sim {habitat_sim.__version__}')"
python -c "import torch; print(f'torch {torch.__version__} MPS: {torch.backends.mps.is_available()}')"
python -c "import transformers; print('transformers OK')"
python -c "import flask; print(f'flask {flask.__version__}')"

echo ""
echo "=== Environment Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Download Replica dataset:"
echo "     bash scripts/download_replica.sh"
echo ""
echo "  2. Start Flask backend:"
echo "     conda activate embodied-nav && python server/app.py"
echo ""
echo "  3. Open frontend:"
echo "     open frontend/index.html"
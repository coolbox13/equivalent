#!/bin/bash
# Setup script for product matching environment
# Solves numpy/scipy/sentence-transformers compatibility issues

echo "🚀 Setting up Product Matching Environment"
echo "=========================================="

# Check if conda is available
if ! command -v conda &> /dev/null; then
    echo "❌ Conda not found. Please install Miniconda or Anaconda first."
    exit 1
fi

# Create environment
echo "📦 Creating conda environment 'product_matching'..."
conda create -n product_matching python=3.13.5  -y

# Activate environment
echo "🔧 Activating environment..."
source $(conda info --base)/etc/profile.d/conda.sh
conda activate product_matching

# Install requirements
echo "📚 Installing compatible dependencies..."
pip install -r requirements.txt

# Verify installation
echo "✅ Verifying installation..."
python -c "
import numpy as np
import pandas as pd
import scipy
from sentence_transformers import SentenceTransformer
print(f'✅ numpy: {np.__version__}')
print(f'✅ pandas: {pd.__version__}')
print(f'✅ scipy: {scipy.__version__}')
print('✅ sentence-transformers: imported successfully')
print('🎉 Environment setup complete!')
"

echo ""
echo "🎯 To use this environment:"
echo "   conda activate product_matching"
echo "   python product_matching_test.py"
echo ""
echo "🔧 To deactivate:"
echo "   conda deactivate"
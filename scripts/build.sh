#!/bin/bash
# Build script for GenieWatch
# Compiles the React frontend before deployment.
# Usage: ./scripts/build.sh

set -e

echo "Building GenieWatch..."

cd frontend
npm ci
npm run build
cd ..

echo "Frontend built successfully at frontend/dist/"

#!/usr/bin/env bash
# Run test coverage across multiple Python versions and combine results
# Usage: ./scripts/coverage-multi-version.sh [--html]

set -e
cd "$(dirname "$0")/.."

VERSIONS="3.12 3.13 3.14"
HTML_REPORT=false

if [[ "$1" == "--html" ]]; then
    HTML_REPORT=true
fi

echo "=== Multi-version coverage collection ==="
rm -f .coverage .coverage.* 2>/dev/null || true

for ver in $VERSIONS; do
    echo ""
    echo ">>> Python $ver"
    COVERAGE_FILE=.coverage.$ver uv run --python $ver --with pytest --with pytest-cov -- \
        python -m pytest tests/ --cov=bytecode_anf --cov-report= -q
done

echo ""
echo "=== Combining coverage data ==="
uv run --python 3.14 --with coverage -- coverage combine .coverage.3.12 .coverage.3.13 .coverage.3.14

echo ""
echo "=== Coverage Report ==="
uv run --python 3.14 --with coverage -- coverage report --show-missing

if $HTML_REPORT; then
    echo ""
    echo "=== Generating HTML report ==="
    uv run --python 3.14 --with coverage -- coverage html -d htmlcov
    echo "Report written to htmlcov/index.html"
fi

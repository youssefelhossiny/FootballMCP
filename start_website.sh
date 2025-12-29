#!/bin/bash
# Start FPL Optimizer Website
# Runs both the FastAPI backend and React frontend

echo "🚀 Starting FPL Optimizer Website..."
echo ""

# Check if we're in the right directory
if [ ! -d "fpl-optimizer" ] || [ ! -d "fpl-website" ]; then
    echo "❌ Error: Run this script from the Football-MCP directory"
    exit 1
fi

# Function to cleanup background processes on exit
cleanup() {
    echo ""
    echo "🛑 Stopping servers..."
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    exit 0
}

trap cleanup SIGINT SIGTERM

# Start FastAPI backend
echo "📡 Starting FastAPI backend on http://localhost:8000..."
cd fpl-optimizer
python -m uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!
cd ..

# Wait for backend to start
sleep 2

# Start React frontend
echo "🌐 Starting React frontend on http://localhost:3000..."
cd fpl-website
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "✅ FPL Optimizer Website is running!"
echo ""
echo "   Frontend: http://localhost:3000"
echo "   Backend:  http://localhost:8000"
echo "   API Docs: http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop both servers"
echo ""

# Wait for processes
wait

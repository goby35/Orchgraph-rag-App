# Production startup script - Backend + Frontend
Write-Host "🚀 Starting GraphRAG Production..." -ForegroundColor Green

# Backend
Write-Host "`n📡 Starting Backend (http://localhost:8000)..." -ForegroundColor Cyan
$backendProc = Start-Process -NoNewWindow -PassThru -FilePath "powershell" -ArgumentList `
    "-Command 'cd d:\Study\uni\25_26\HKII\graphRAG; .venv\Scripts\activate; uvicorn api.main:app --port 8000'"

# Frontend 
Write-Host "🎨 Starting Frontend (http://localhost:3000)..." -ForegroundColor Cyan
$frontendProc = Start-Process -NoNewWindow -PassThru -FilePath "powershell" -ArgumentList `
    "-Command 'cd d:\Study\uni\25_26\HKII\graphRAG\frontend; npm run build; npm run start'"

Write-Host "`n✓ Both services started!" -ForegroundColor Green
Write-Host "  Backend:  http://localhost:8000/docs" -ForegroundColor Yellow
Write-Host "  Frontend: http://localhost:3000" -ForegroundColor Yellow
Write-Host "`nPress Ctrl+C to stop both services..." -ForegroundColor Gray

# Keep script alive
Wait-Process -Id $backendProc.Id, $frontendProc.Id

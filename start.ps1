# Starts the Django API (port 8000) and the React app (port 5173) in two windows.
$root = $PSScriptRoot
Start-Process powershell -ArgumentList '-NoExit', '-Command', "Set-Location '$root\backend'; .\.venv\Scripts\python manage.py runserver 127.0.0.1:8000"
Start-Process powershell -ArgumentList '-NoExit', '-Command', "Set-Location '$root\frontend'; npx vite --port 5173"
Start-Sleep 4
Start-Process 'http://127.0.0.1:5173'

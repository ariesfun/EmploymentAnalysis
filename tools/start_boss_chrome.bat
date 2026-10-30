@echo off
REM Start an isolated Chrome with remote debugging for BOSS CDP smoke test.
REM Double-click this file, then log in to BOSS in the opened window.
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9223 --user-data-dir=C:\temp\boss-profile-9223 "https://www.zhipin.com/web/geek/jobs?query=Java&city=101010100"
echo.
echo Chrome started with remote debugging on port 9223.
echo 1) Log in to BOSS in the opened window (scan QR code).
echo 2) Keep that window open.
echo 3) Tell the assistant "login done" so it can run the verification.
echo.
pause

@echo off
REM ===================================================================
REM  Lets the doorbell phone check whether TARS is awake.
REM
REM  RIGHT-CLICK this file and choose "Run as administrator".
REM
REM  What it opens: inbound TCP port 8767, ONLY from devices on your own
REM  home network, ONLY on the Private network profile. That port can say
REM  one word -- "TARS" -- and nothing else. It reads nothing, changes
REM  nothing, and has no other addresses.
REM
REM  Your dashboard (camera, shutdown, school password) stays bound to
REM  the PC itself and is NOT opened by this.
REM
REM  To undo it, run this file again and choose R.
REM ===================================================================
echo.
echo   TARS doorbell -- firewall permission
echo.
echo   [A] Allow the doorbell to see TARS (port 8767, home network only)
echo   [R] Remove that permission again
echo.
set /p choice=  Type A or R and press Enter:

if /i "%choice%"=="R" goto remove

netsh advfirewall firewall delete rule name="TARS heartbeat" >nul 2>&1
netsh advfirewall firewall add rule name="TARS heartbeat" dir=in action=allow protocol=TCP localport=8767 remoteip=LocalSubnet profile=private description="Lets the TARS doorbell phone check whether TARS is awake. Answers the single word TARS and nothing else."
if errorlevel 1 (
  echo.
  echo   FAILED. You need to RIGHT-CLICK this file and pick
  echo   "Run as administrator" -- a normal double-click cannot do it.
) else (
  echo.
  echo   Done. The doorbell can now see whether TARS is awake.
)
goto end

:remove
netsh advfirewall firewall delete rule name="TARS heartbeat"
echo.
echo   Removed.

:end
echo.
pause

@echo off
REM Pfad zur Aktivierung der virtuellen Umgebung (venv)
call env\Scripts\activate.bat

REM Überprüfen, ob die Aktivierung erfolgreich war (optional, aber nützlich)
if exist env\Scripts\pythonw.exe (
    echo Virtuelle Umgebung aktiviert.
    
    REM Ausführung des Python-Skripts
    python AudioRecorder.py
) else (
    echo FEHLER: Die virtuelle Umgebung konnte nicht aktiviert werden. Stelle sicher, dass der Pfad stimmt.
)

REM Deaktivierung der Umgebung (optional)
call deactivate

echo Skript-Ausführung abgeschlossen.
pause
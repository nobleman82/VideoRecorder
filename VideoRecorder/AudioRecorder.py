# -*- coding: utf-8 -*-
import soundcard as sc
import numpy as np
import soundfile as sf
import time
import sys

# Konfiguration der Aufnahme
SAMPLERATE = 44100  # Standard-Abtastrate
DURATION_SECONDS = 10 # Aufnahmedauer in Sekunden
CHANNELS = 2        # Stereo-Aufnahme
FILENAME = "system_audio_aufnahme.wav"
# Hinweis: Die Puffergröße (Blocksize) wird automatisch von SoundCard/WASAPI verwaltet

def find_loopback_device(speaker_name):
    """
    Sucht das korrespondierende Loopback-Aufnahmegerät basierend auf dem Namen des Standard-Ausgabegeräts.
    Gibt ein Microphone-Objekt (das als Loopback-Quelle dient) oder None zurück.
    """
    print(f"Suche Loopback-Quelle für: '{speaker_name}'...")
    
    # Ruft alle Mikrofone/Aufnahmegeräte ab, einschließlich der Loopback-Quellen.
    all_mics = sc.all_microphones(include_loopback=True)
    
    # Erwartete Namen für Loopback-Geräte sind oft identisch mit dem Lautsprechernamen
    # oder enthalten Begriffe wie 'Monitor' oder den Lautsprechernamen selbst.
    speaker_name_lower = speaker_name.strip().lower()
    
    best_match = None
    
    for mic in all_mics:
        mic_name_lower = mic.name.strip().lower()
        
        # Exakter Match (manchmal wird das Wiedergabegerät selbst als Loopback gelistet)
        if mic_name_lower == speaker_name_lower:
             return mic 
             
        # Alternativ: Match, wenn der Sprechername im Mikronamen enthalten ist (häufig für Monitore)
        if speaker_name_lower in mic_name_lower:
             # Wenn wir ein 'Monitor' oder 'Mix' Gerät finden, ist das wahrscheinlich der richtige Loopback
             if 'monitor' in mic_name_lower or 'mix' in mic_name_lower:
                 return mic
             # Ansonsten speichern wir es als besten Treffer, falls kein besseres gefunden wird
             best_match = mic
    
    # Rückgabe des besten Matches (oder None)
    return best_match


def record_system_audio():
    """
    Erkennt das Standard-Ausgabegerät, zeichnet dessen Audio-Mix auf (Loopback) 
    und speichert es in einer WAV-Datei.
    """
    try:
        # 1. Standard-Ausgabegerät erkennen (Ihr USB-Kopfhörerausgang)
        default_speaker = sc.default_speaker()
        speaker_name = default_speaker.name
        print("-" * 50)
        print(f"Standard-Ausgabegerät erkannt: {speaker_name}")
        
        # 2. Explizit nach dem Loopback-Mikrofon suchen (FIX für den '_Speaker' object has no attribute 'record' Fehler)
        source_device = find_loopback_device(speaker_name)
        
        if source_device is None:
            # Falls die spezifische Suche fehlschlägt, geben wir eine informative Fehlermeldung aus
            print(f"FEHLER: Das Loopback-Aufnahmegerät für '{speaker_name}' konnte nicht explizit gefunden werden.", file=sys.stderr)
            print("Mögliche Ursachen:", file=sys.stderr)
            print(" - Die 'soundcard'-Bibliothek konnte das korrekte WASAPI-Loopback-Gerät nicht identifizieren.", file=sys.stderr)
            print(" - Das Gerät muss möglicherweise manuell in der Windows-Systemsteuerung aktiviert werden (z.B. 'Stereo Mix' oder 'Wave Out Mix', falls verfügbar).", file=sys.stderr)
            print(" - Versuchen Sie, 'sc.all_microphones(include_loopback=True)' zu drucken, um die verfügbaren Loopback-Namen zu überprüfen.", file=sys.stderr)
            return

        # 3. Aufnahme starten
        print(f"Verwende das Loopback-Gerät: '{source_device.name}' als Quelle.")
        print(f"Starte Aufnahme für {DURATION_SECONDS} Sekunden...")
        print("!!! ACHTUNG: Jetzt müssen Sie Audio auf Ihrem PC abspielen (Chrome, Media Player etc.) !!!")
        
        # Die record-Methode auf einem Microphone-Objekt (das die Loopback-Quelle ist)
        audio_data = source_device.record(
            samplerate=SAMPLERATE, 
            numframes=SAMPLERATE * DURATION_SECONDS, 
            channels=CHANNELS
        )
        
        print("Aufnahme beendet.")
        
        # 4. Speichern der Daten
        sf.write(FILENAME, audio_data, SAMPLERATE)
        
        print("-" * 50)
        print(f"Erfolgreich gespeichert unter: {FILENAME}")
        print(f"Aufgenommene Datenform: {audio_data.shape}")

    except Exception as e:
        print("-" * 50)
        print(f"FEHLER bei der Audio-Aufnahme: {e}", file=sys.stderr)
        print("Mögliche Ursachen:")
        print("1. 'soundcard' konnte nicht auf die WASAPI-Schnittstelle zugreifen (Versuchen Sie, das Skript als Administrator auszuführen).")
        print("2. Allgemeine Initialisierungsprobleme (z. B. fehlende Berechtigungen oder gesperrter exklusiver Modus).")
        print("-" * 50)


if __name__ == "__main__":
    record_system_audio()

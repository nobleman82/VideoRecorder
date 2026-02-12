
import cv2
import mss
import numpy as np
import threading
import time
import tkinter as tk
import subprocess 
import soundcard as sc
import soundfile as sf
import sys
import os 
import json

# --- Konfiguration ---
VIDEO_FILENAME = "aufnahme.avi"
AUDIO_FILENAME = "aufnahme.wav"
OUTPUT_FILENAME = "output.mp4" 
TIMESTAMP_FILENAME = "timestamps.json" # Neue Datei für Zeitstempel
FPS = 30 # Standard-Framerate für flüssige Bewegungen
FOURCC = cv2.VideoWriter_fourcc(*'mp4v') # Codec für Videoausgabe (wird für FFmpeg benötigt)
SAMPLERATE = 44100  # Abtastrate für Audio
CHANNELS = 2        # Kanäle (Stereo)
# ERHÖHT: Größere Blockgröße gibt dem Audiotreiber mehr Puffer, um Diskontinuitäten bei langen Aufnahmen zu vermeiden.
BLOCKSIZE_MS = 250  # Audio-Blockgröße in Millisekunden (optimiert von 100 auf 250) 

# Die manuelle Korrektur des Audio-Video-Drifts (AUDIO_SYNC_OFFSET_S) ist nicht mehr nötig.

# Globale Variablen zur Steuerung der Threads
stop_recording = threading.Event()
# Wir verwenden eine Barrier, um Video- und Audio-Thread gleichzeitig zu starten (2 Teilnehmer)
start_barrier = threading.Barrier(2) 
video_out = None
monitor_area = None
root_window = None

# --- FFmpeg MUXING FUNKTION ---

def mux_files_with_ffmpeg(video_path, audio_path, output_path, timestamp_path):
    """Führt Video und Audio mit FFmpeg zusammen unter Berücksichtigung der Zeitstempel."""
    
    # Prüfen, ob temporäre Dateien existieren
    if not os.path.exists(video_path) or not os.path.exists(audio_path) or not os.path.exists(timestamp_path):
        print("FEHLER: Eine oder mehrere Quelldateien (Video, Audio oder Zeitstempel) fehlen für das Muxing.", file=sys.stderr)
        return
    
    # 1. Zeitstempel laden
    try:
        with open(timestamp_path, 'r') as f:
            timestamps = json.load(f)
    except Exception as e:
        print(f"FEHLER: Konnte Zeitstempel nicht laden: {e}", file=sys.stderr)
        return

    if not timestamps:
        print("FEHLER: Keine Zeitstempel gefunden, kann nicht synchronisieren.", file=sys.stderr)
        return
        
    # 2. Start-Offset berechnen (Differenz zwischen dem allerersten Video-Frame und der Audio-Aufnahme)
    # Da die Barriere fast gleichzeitig startet, ist der erste Zeitstempel des Videos der beste Anhaltspunkt.
    # Wir nehmen an, dass der Audio-Puffer sofort nach start_barrier befüllt wird (was bei soundcard der Fall ist).
    
    # Der Offset, den wir benötigen, ist 0. Wir verwenden die Zeitstempel, um die Länge zu bestimmen.

    # 3. FFmpeg-Input-Datei für Video-Delay erstellen
    # FFmpeg kann mit einer Datei arbeiten, die Informationen über die Dauer jedes Frames enthält.
    # Hier verwenden wir die Zeitstempel, um eine Input-Liste zu erstellen (Dies ist jedoch sehr komplex in FFmpeg)
    # Die einfachere Methode ist, die Startzeit zu bestimmen und die Rate zu korrigieren, aber wir bleiben bei der robusten Methode:
    
    # Berechne die tatsächliche Videodauer basierend auf dem letzten Zeitstempel minus dem ersten
    video_duration = timestamps[-1] - timestamps[0]
    
    # Berechne die durchschnittliche Frame-Dauer
    avg_frame_duration = video_duration / len(timestamps)
    
    # Berechne die "korrigierte" Framerate (fps) für FFmpeg
    # Diese korrigierte Rate sorgt dafür, dass die Gesamtdauer des Videos der tatsächlichen Aufnahmezeit entspricht
    corrected_fps = len(timestamps) / video_duration
    
    print(f"\nStarte Zusammenführung (Muxing) mit korrigierter Rate von {corrected_fps:.2f} FPS...")
    
    # FFmpeg-Befehl: 
    # NEU: -r {corrected_fps} wendet die korrigierte Framerate auf den Input 0 (Video) an.
    command = [
        "ffmpeg",
        "-r", f"{corrected_fps}", # Korrigierte Rate für den Video-Input
        "-i", video_path,
        "-i", audio_path,
        "-map", "0:v:0", # Nimm den ersten Videostream von Input 0
        "-map", "1:a:0", # Nimm den ersten Audiostream von Input 1
        "-c:v", "libx264",
        "-crf", "23", 
        "-preset", "veryfast", 
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest", # Beendet die Codierung, sobald der kürzeste Input Stream endet
        "-y", # Überschreibt die Ausgabedatei ohne Nachfrage
        output_path
    ]
    
    try:
        # Ausführen des FFmpeg-Befehls
        process = subprocess.run(command, check=True, capture_output=True, text=True)
        print(f"Erfolgreich zu {output_path} gemuxt und kodiert.")
        
        # Temporäre Dateien aufräumen
        os.remove(video_path)
        os.remove(audio_path)
        os.remove(timestamp_path)
        print(f"Temporäre Dateien ({video_path}, {audio_path} und {timestamp_path}) gelöscht.")
        
    except subprocess.CalledProcessError as e:
        print(f"FEHLER: FFmpeg-Befehl fehlgeschlagen. Ist FFmpeg installiert und im PATH?", file=sys.stderr)
        print(f"Befehl: {' '.join(command)}", file=sys.stderr)
        print(f"Fehlermeldung (stdout): {e.stdout}", file=sys.stderr)
        print(f"Fehlermeldung (stderr): {e.stderr}", file=sys.stderr)
    except FileNotFoundError:
        print("FEHLER: FFmpeg-Programm wurde nicht gefunden. Bitte stellen Sie sicher, dass FFmpeg installiert und in Ihrem System-PATH ist.", file=sys.stderr)

# --- SOUNDCARD LOOPBACK LOGIK ---

def find_loopback_device(speaker_name):
    """
    Sucht das korrespondierende Loopback-Aufnahmegerät basierend auf dem Namen des Standard-Ausgabegeräts.
    Gibt ein Microphone-Objekt (das als Loopback-Quelle dient) oder None zurück.
    """
    all_mics = sc.all_microphones(include_loopback=True)
    speaker_name_lower = speaker_name.strip().lower()
    
    # Suchen Sie nach dem Gerät, dessen Name dem Speaker-Namen entspricht oder 'Monitor'/'Mix' enthält.
    for mic in all_mics:
        mic_name_lower = mic.name.strip().lower()
        
        # Exakter Match oder ein Monitor/Mix-Gerät, das den Namen enthält
        if mic_name_lower == speaker_name_lower or \
           (speaker_name_lower in mic_name_lower and ('monitor' in mic_name_lower or 'mix' in mic_name_lower)):
             return mic 
             
    # Falls soundcard keine klare Loopback-Quelle als 'Microphone' erkennt, 
    # kann die Aufnahme trotzdem fehlschlagen.
    return None

# --- AUDIO AUFNAHME FUNKTION ---

def record_audio():
    """Nimmt System-Audio über WASAPI Loopback auf (ersetzt sounddevice-Logik)."""
    
    # Warten auf das Startsignal des GUI-Threads, um Synchronisation zu gewährleisten
    start_barrier.wait() 
    
    try:
        # 1. Standard-Ausgabegerät erkennen
        default_speaker = sc.default_speaker()
        speaker_name = default_speaker.name
        
        # 2. Explizit nach dem Loopback-Mikrofon suchen
        source_device = find_loopback_device(speaker_name)
        
        if source_device is None:
            print(f"FEHLER: Loopback-Gerät für '{speaker_name}' konnte nicht gefunden werden.", file=sys.stderr)
            print("Überprüfen Sie, ob 'Stereo Mix' oder eine virtuelle Loopback-Quelle aktiviert ist.", file=sys.stderr)
            stop_recording.set()
            return
            
        print(f"Verwende Loopback-Gerät: '{source_device.name}'. Aufnahme gestartet.")
        
        # Stream öffnen und Daten in Blöcken aufnehmen
        samplerate = SAMPLERATE
        channels = CHANNELS
        audio_data_chunks = []
        
        # Blockgröße für die Aufnahme: (Bsp. 250ms)
        blocksize = int(samplerate * (BLOCKSIZE_MS / 1000.0)) 

        with source_device.recorder(samplerate=samplerate, channels=channels, blocksize=blocksize) as mic_recorder:
            
            while not stop_recording.is_set():
                # Datenblock aus dem Stream lesen (blockiert, bis der Block gefüllt ist)
                data = mic_recorder.record()
                audio_data_chunks.append(data.copy())
                # Keine manuelle Pause hier, da mic_recorder.record() die Zeitsteuerung übernimmt
                
    except Exception as e:
        print(f"Fehler bei der Audioaufnahme: {e}", file=sys.stderr)
        stop_recording.set()
        return

    print("\nAudioaufnahme wird gespeichert...")
    if audio_data_chunks:
        audio_array = np.concatenate(audio_data_chunks, axis=0)
        sf.write(AUDIO_FILENAME, audio_array, samplerate)
        print(f"Audio unter {AUDIO_FILENAME} gespeichert.")
    else:
        print("Kein Audio aufgenommen.")


# --- VIDEO AUFNAHME FUNKTION ---

def record_video():
    """Nimmt den angegebenen Bildschirmbereich auf und speichert jeden Frame mit Zeitstempel."""
    global video_out
    
    timestamps = [] # Liste zur Speicherung der Zeitstempel
    
    # Warten auf das Startsignal des Audio-Threads, um Synchronisation zu gewährleisten
    start_barrier.wait() 
    
    sct = mss.mss()
    print("Videoaufnahme gestartet.")
    
    if monitor_area:
        # WICHTIG: Verwende eine sehr hohe Framerate (z.B. 1000) für den AVI-Container, 
        # damit FFmpeg die tatsächliche Frame-Dauer später neu berechnet. 
        # Alternativ können wir die ursprüngliche FPS verwenden und später korrigieren.
        # Wir bleiben bei der Ziel-FPS, lassen aber die Zeitsteuerung von FFmpeg korrigieren.
        video_out = cv2.VideoWriter(VIDEO_FILENAME, FOURCC, FPS, (monitor_area['width'], monitor_area['height']))
        
    frame_duration = 1.0 / FPS # Zielzeit pro Frame (z.B. 1/30 = 0.0333s)
    
    while not stop_recording.is_set():
        start_time = time.time()
        
        if not monitor_area:
            time.sleep(0.1)
            continue
            
        try:
            screenshot = sct.grab(monitor_area)
            frame = np.array(screenshot)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            video_out.write(frame)
            timestamps.append(start_time) # Zeitstempel des aufgenommenen Frames speichern
            
        except Exception as e:
            print(f"Fehler beim Frame-Grab: {e}", file=sys.stderr)
            time.sleep(0.1)
        
        # FRAMERATE-KORREKTUR: Berechnet die verbleibende Zeit, um die Ziel-FPS zu treffen
        elapsed_time = time.time() - start_time
        sleep_time = frame_duration - elapsed_time
        if sleep_time > 0:
            time.sleep(sleep_time)
            
    print("Videoaufnahme wird beendet...")
    if video_out:
        video_out.release()
    cv2.destroyAllWindows()
    print(f"Video unter {VIDEO_FILENAME} gespeichert.")
    
    # Zeitstempel speichern, nachdem die Aufnahme beendet ist
    try:
        with open(TIMESTAMP_FILENAME, 'w') as f:
            json.dump(timestamps, f)
        print(f"Zeitstempel unter {TIMESTAMP_FILENAME} gespeichert.")
    except Exception as e:
        print(f"FEHLER beim Speichern der Zeitstempel: {e}", file=sys.stderr)


# --- GUI FUNKTIONEN ---

def start_threads_and_gui_switch():
    """Startet die Aufnahme-Threads und wechselt die GUI."""
    global monitor_area
    
    # Erfassen der endgültigen Fenstergeometrie
    geom = root_window.winfo_geometry()
    parts = geom.split('x')
    width = int(parts[0])
    height = int(parts[1].split('+')[0])
    x = int(parts[1].split('+')[1])
    y = int(parts[1].split('+')[2])
    
    monitor_area = {"top": y, "left": x, "width": width, "height": height}
    
    # GUI-Fenster auf den Aufnahmemodus umschalten
    root_window.geometry("150x50+50+50")
    root_window.overrideredirect(False)
    root_window.attributes('-alpha', 1.0)
    root_window.title("Aufnahme läuft")

    # Buttons umschalten
    for widget in root_window.winfo_children():
        widget.destroy()

    stop_button = tk.Button(root_window, text="Stop Aufnahme", command=stop_recording_and_cleanup)
    stop_button.pack(fill=tk.BOTH, expand=True)

    # Threads starten
    audio_thread = threading.Thread(target=record_audio)
    video_thread = threading.Thread(target=record_video)
    
    audio_thread.start()
    video_thread.start()
    # Warten auf die Threads wird jetzt von start_barrier.wait() übernommen.

def stop_recording_and_cleanup():
    """Beendet die Aufnahme und schließt das Fenster."""
    stop_recording.set()
    # Da die Threads noch kurz brauchen, um ihre Schleifen zu verlassen, 
    # warten wir kurz, bevor wir das Fenster zerstören.
    root_window.after(500, root_window.destroy) 

def get_next_available_filename(base_filename):
    """
    Generiert einen eindeutigen Dateinamen im Format 'name_x.mp4'.
    Wenn 'output.mp4' existiert, wird 'output_1.mp4' geprüft, dann 'output_2.mp4', usw.

    :param base_filename: Der ursprüngliche Dateiname (z.B. "output.mp4").
    :return: Der erste nicht existierende Dateiname.
    """
    # 1. Initialprüfung
    if not os.path.exists(base_filename):
        # Die Originaldatei existiert nicht, wir können sie verwenden.
        return base_filename

    # 2. Basisname und Erweiterung extrahieren
    # z.B. aus "output.mp4" wird name="output", ext=".mp4"
    name, ext = os.path.splitext(base_filename)
    counter = 1

    # 3. Schleife, um den nächsten freien Zähler zu finden
    while True:
        # Generiere den potenziellen nächsten Dateinamen: "output_1.mp4", "output_2.mp4", ...
        new_filename = f"{name}_{counter}{ext}"

        # Prüfe, ob die generierte Datei existiert
        if not os.path.exists(new_filename):
            # Der Name existiert nicht, gib ihn zurück. Die Schleife wird beendet.
            return new_filename
        
        # Die Datei existiert, erhöhe den Zähler und prüfe im nächsten Schleifendurchlauf.
        counter += 1


def create_gui():
    """Erstellt die Benutzeroberfläche zur Auswahl des Aufnahmebereichs."""
    global root_window
    root_window = tk.Tk()
    root_window.title("Bereich auswählen")
    root_window.geometry("800x600+100+100")
    
    # Initialisierung für Transparenz und Rahmenlosigkeit
    root_window.overrideredirect(True)
    root_window.attributes('-alpha', 0.5)
    root_window.attributes('-topmost', True)
    
    # Haupt-Frame für den Aufnahmebereich
    frame = tk.Frame(root_window, highlightbackground="red", highlightthickness=2)
    frame.pack(fill=tk.BOTH, expand=True)

    # Label-Hinweis
    label = tk.Label(frame, text="Größe und Position anpassen.\n'Start' klicken, um Aufnahme zu starten.\nZiehen Sie die Ecke, um die Größe zu ändern.", bg="white", fg="black")
    label.place(relx=0.5, rely=0.5, anchor="center")
    
    # Start-Button
    start_button = tk.Button(root_window, text="Start Aufnahme", command=start_threads_and_gui_switch)
    start_button.pack(side=tk.BOTTOM, padx=5, pady=5)
    
    # Drag-Funktionalität
    def start_drag(event):
        root_window.x = event.x
        root_window.y = event.y

    def drag(event):
        x = root_window.winfo_x() + event.x - root_window.x
        y = root_window.winfo_y() + event.y - root_window.y
        root_window.geometry(f"+{x}+{y}")
        
    frame.bind("<Button-1>", start_drag)
    frame.bind("<B1-Motion>", drag)
    
    # Resizing-Funktionalität (untere rechte Ecke)
    resize_handle = tk.Frame(root_window, width=10, height=10, bg="red", cursor="size_nw_se")
    resize_handle.place(relx=1.0, rely=1.0, anchor="se")
    
    def start_resize(event):
        root_window.start_x = event.x_root
        root_window.start_y = event.y_root
        root_window.start_width = root_window.winfo_width()
        root_window.start_height = root_window.winfo_height()

    def resize(event):
        dx = event.x_root - root_window.start_x
        dy = event.y_root - root_window.start_y
        new_width = max(100, root_window.start_width + dx)
        new_height = max(100, root_window.start_height + dy)
        root_window.geometry(f"{new_width}x{new_height}")

    resize_handle.bind("<Button-1>", start_resize)
    resize_handle.bind("<B1-Motion>", resize)

    root_window.mainloop()

if __name__ == "__main__":
    print("Erstelle GUI zur Auswahl des Aufnahmebereichs...")
    create_gui()
  
    OUTPUT_FILENAME = get_next_available_filename(OUTPUT_FILENAME)

    # Automatisches Muxing mit FFmpeg
    mux_files_with_ffmpeg(VIDEO_FILENAME, AUDIO_FILENAME, OUTPUT_FILENAME, TIMESTAMP_FILENAME)
    
    print("\nAlle Vorgänge abgeschlossen.")

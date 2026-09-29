"""Graba el video de demostración de Cuadrador (herramienta para desarrollar, no parte de la app).

Usa Playwright: una librería que maneja un navegador desde Python (abre páginas, hace
clic, baja la pantalla). Está instalada SOLO en el venv y NO está en requirements.txt,
porque la app no la necesita para funcionar.

Instalación (una sola vez):
    pip install playwright
    python -m playwright install chromium
    (Ubuntu necesita además: sudo apt install -y libnss3 libnspr4)

Uso:
    python tools/record_demo.py

Cómo graba: en vez de usar la grabación de video de Playwright (que comprime con
pérdida y mete "ruido" en cada cuadro, lo que hace enorme al GIF), toma una captura
exacta (PNG) de la pantalla 10 veces por segundo mientras la página se mueve, y
repite la misma captura durante las pausas. Con esas imágenes, ffmpeg arma:
    docs/demo.webm, docs/demo.mp4 y docs/demo.gif (960 px de ancho, 10 fps, máximo 8 MB)

El recorrido: inicio -> "Try with sample data" -> baja despacio por el resultado ->
vuelve al inicio -> "Try the example with an error" -> la causa del -$90.00.
Solo usa los datos inventados de sample_data/ y sample_data_error/.
"""

import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
URL = "http://127.0.0.1:5001"
SIZE = {"width": 1280, "height": 800}
FPS = 10
MAX_SECONDS = 60
GIF_WIDTH = 960
GIF_MAX_MB = 8


# ---------- la app ----------

def port_in_use(port=5001):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_app():
    """Arranca app.py y espera a que responda."""
    if port_in_use():
        sys.exit("Port 5001 is already in use. Stop the running app first, then try again.")
    app = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        if port_in_use():
            return app
        time.sleep(0.25)
    app.terminate()
    sys.exit("The app did not start on port 5001.")


# ---------- la "cámara": capturas cuadro por cuadro ----------

class Camera:
    """Guarda cuadros numerados (frame_00001.png, ...). Cada cuadro dura 1/FPS segundos."""

    def __init__(self, page, folder):
        self.page = page
        self.folder = folder
        self.count = 0

    def shoot(self, repeat=1):
        """Una captura de la pantalla, repetida `repeat` cuadros."""
        image = self.page.screenshot()
        for _ in range(repeat):
            self.count += 1
            (self.folder / f"frame_{self.count:05d}.png").write_bytes(image)

    def pause(self, seconds):
        """La pantalla quieta: la misma imagen durante `seconds` segundos."""
        self.shoot(repeat=round(seconds * FPS))

    def scroll_to_y(self, target, seconds=1.5):
        """Bajar (o subir) despacio: un cuadro por cada paso del movimiento."""
        start = self.page.evaluate("window.scrollY")
        steps = max(1, round(seconds * FPS))
        for step in range(1, steps + 1):
            # Movimiento suave: acelera al principio y frena al final
            progress = step / steps
            eased = progress * progress * (3 - 2 * progress)
            self.page.evaluate("y => window.scrollTo(0, y)", start + (target - start) * eased)
            self.shoot()

    def scroll_to(self, selector, seconds=1.5, margin=90):
        """Bajar despacio hasta que el elemento quede cerca del borde de arriba."""
        target = self.page.evaluate(
            """([selector, margin]) => {
                const element = document.querySelector(selector);
                const top = element.getBoundingClientRect().top + window.scrollY - margin;
                return Math.max(0, Math.min(top, document.documentElement.scrollHeight - window.innerHeight));
            }""", [selector, margin])
        self.scroll_to_y(target, seconds)

    @property
    def seconds(self):
        return self.count / FPS


def click(page, role, name):
    page.get_by_role(role, name=name).first.click()
    page.wait_for_load_state("networkidle")


# ---------- el guion del video ----------

def record(frames_folder):
    """Recorre la app y deja los cuadros en `frames_folder`. Devuelve cuántos segundos dura."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport=SIZE)
        camera = Camera(page, frames_folder)

        # 1. La página de inicio
        page.goto(URL)
        camera.pause(3)

        # 2. "Try with sample data": cuadra en $0.00
        click(page, "button", "Try with sample data")
        camera.pause(3)

        # 3. Bajar despacio: los contadores y la sección Review con sus motivos
        camera.scroll_to(".counts", seconds=1.5, margin=380)
        camera.pause(2.5)
        camera.scroll_to("h2", seconds=2)
        camera.pause(3)
        camera.scroll_to_y(page.evaluate("window.scrollY") + 420, seconds=2)
        camera.pause(3)

        # 4. Volver al inicio
        camera.scroll_to_y(0, seconds=1.2)
        click(page, "link", "New reconciliation")
        camera.pause(2)

        # 5. "Try the example with an error": la diferencia de -$90.00 y su causa
        click(page, "button", "Try the example with an error")
        camera.pause(4)

        # 6. La línea del cheque en Review: $540 en el banco, $450 en los libros
        camera.scroll_to("h2", seconds=2)
        page.evaluate("""() => {
            const row = [...document.querySelectorAll('tr')].find(r => r.textContent.includes('digits look swapped'));
            if (row) { row.style.outline = '3px solid #991b1b'; row.style.outlineOffset = '-3px'; }
        }""")
        camera.pause(3.5)
        camera.scroll_to_y(0, seconds=1.2)
        camera.pause(2.5)

        browser.close()
        return camera.seconds


# ---------- ffmpeg ----------

def run_ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def make_videos(frames_folder):
    """Arma demo.webm, demo.mp4 y demo.gif a partir de los cuadros. Devuelve los colores del GIF."""
    frames = ["-framerate", str(FPS), "-i", str(frames_folder / "frame_%05d.png")]
    run_ffmpeg(*frames, "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "34", "-row-mt", "1",
               "-pix_fmt", "yuv420p", str(DOCS / "demo.webm"))
    run_ffmpeg(*frames, "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p",
               "-movflags", "+faststart", str(DOCS / "demo.mp4"))

    # GIF: una paleta de colores para todo el video; sin tramado (la interfaz usa colores
    # planos) y guardando solo el rectángulo que cambia entre un cuadro y el siguiente.
    gif = DOCS / "demo.gif"
    for colors in (128, 64, 32):
        palette_filter = (f"scale={GIF_WIDTH}:-1:flags=lanczos,split[a][b];"
                          f"[a]palettegen=max_colors={colors}:stats_mode=full[p];"
                          f"[b][p]paletteuse=dither=none:diff_mode=rectangle")
        run_ffmpeg(*frames, "-vf", palette_filter, str(gif))
        if gif.stat().st_size <= GIF_MAX_MB * 1024 * 1024:
            return colors
    sys.exit(f"The GIF is still larger than {GIF_MAX_MB} MB. Make the video shorter.")


def main():
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg is not installed. On Ubuntu: sudo apt update && sudo apt install -y ffmpeg")
    DOCS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        frames_folder = Path(folder)
        app = start_app()
        try:
            seconds = record(frames_folder)
        finally:
            app.terminate()
            app.wait()
        if seconds > MAX_SECONDS:
            sys.exit(f"The video lasts {seconds:.1f} s, more than {MAX_SECONDS} s. Shorten the pauses.")
        colors = make_videos(frames_folder)

    for name in ("demo.webm", "demo.mp4", "demo.gif"):
        path = DOCS / name
        print(f"docs/{name}: {path.stat().st_size / 1024 / 1024:.2f} MB")
    print(f"Duration: {seconds:.1f} s at {FPS} fps. GIF: {GIF_WIDTH} px wide, {colors} colors.")


if __name__ == "__main__":
    main()

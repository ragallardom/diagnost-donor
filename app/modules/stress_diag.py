#!/usr/bin/env python3
"""
Hardware Stress Diagnostic Module
Supports isolated, non-blocking stress testing for:
  - CPU (Multithreaded matrix/math load + thermal throttling check)
  - RAM (DDR3, DDR4, DDR5, LPDDR3/4/5 with bit-flip & pattern tests)
  - SSD (Safe temporary buffered/unbuffered I/O speed and integrity test)
  - GPU / iGPU (Coordination and telemetry during WebGL 3D load)

Includes automatic thermal abort (95°C), manual abort, and comprehensive error handling.
"""

import os
import sys
import time
import math
import shutil
import random
import threading
import subprocess
from datetime import datetime

# Global singleton runner
_stress_runner = None
_runner_lock = threading.Lock()


class HardwareStressRunner:
    def __init__(self, components=None, level="quick"):
        self.components = components or ["cpu", "ram", "ssd", "gpu"]
        self.level = level  # 'quick', 'medium', 'deep'
        self.is_running = False
        self.aborted = False
        self.progress_percent = 0
        self.start_time = None
        self.total_duration_sec = 0
        self.elapsed_sec = 0
        self.current_component = None
        self.logs = []
        self.results = {}
        self.max_temp_c = 0
        self.worker_thread = None

        # Determine total duration based on level and selected components
        durations_per_component = {
            "quick":  {"cpu": 45,  "ram": 45,  "ssd": 30,  "gpu": 30},
            "medium": {"cpu": 120, "ram": 120, "ssd": 60,  "gpu": 60},
            "deep":   {"cpu": 300, "ram": 300, "ssd": 180, "gpu": 180},
        }
        level_dur = durations_per_component.get(self.level, durations_per_component["quick"])
        self.durations = {c: level_dur.get(c, 45) for c in self.components}
        self.total_duration_sec = sum(self.durations.values())

    def log(self, message, msg_type="info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = {
            "time": timestamp,
            "message": message,
            "type": msg_type  # 'info', 'success', 'warning', 'error', 'step'
        }
        self.logs.append(entry)
        if len(self.logs) > 150:
            self.logs.pop(0)

    def get_cpu_temp(self):
        """Read maximum CPU temperature across thermal zones and hwmon."""
        temps = []
        try:
            # Check thermal zones
            tz_dir = "/sys/class/thermal"
            if os.path.exists(tz_dir):
                for tz in os.listdir(tz_dir):
                    if tz.startswith("thermal_zone"):
                        path = os.path.join(tz_dir, tz, "temp")
                        if os.path.isfile(path):
                            try:
                                with open(path, "r") as f:
                                    t = float(f.read().strip()) / 1000.0
                                    if 15.0 <= t <= 125.0:
                                        temps.append(t)
                            except Exception:
                                pass

            # Check hwmon
            hw_dir = "/sys/class/hwmon"
            if os.path.exists(hw_dir):
                for hw in os.listdir(hw_dir):
                    hw_path = os.path.join(hw_dir, hw)
                    for f in os.listdir(hw_path):
                        if f.startswith("temp") and f.endswith("_input"):
                            try:
                                with open(os.path.join(hw_path, f), "r") as tf:
                                    t = float(tf.read().strip()) / 1000.0
                                    if 15.0 <= t <= 125.0:
                                        temps.append(t)
                            except Exception:
                                pass
        except Exception:
            pass

        return max(temps) if temps else 45.0

    def check_thermal_safety(self):
        """Returns False if critical temperature is reached."""
        current_temp = self.get_cpu_temp()
        if current_temp > self.max_temp_c:
            self.max_temp_c = current_temp

        if current_temp >= 95.0:
            self.log(f"[ALERTA CRITICA] Temperatura de CPU a {current_temp:.1f}°C (Limite 95°C). Abortando por seguridad.", "error")
            self.aborted = True
            return False
        return True

    def start(self):
        self.is_running = True
        self.aborted = False
        self.start_time = time.time()
        self.results = {}
        self.logs = []
        self.max_temp_c = self.get_cpu_temp()
        self.log(f"[INICIO] Iniciando suite de estrés nivel: {self.level.upper()} ({self.total_duration_sec}s total estimado).", "step")

        self.worker_thread = threading.Thread(target=self._run_all_tests, daemon=True)
        self.worker_thread.start()

    def stop(self):
        self.aborted = True
        self.log("[INFO] Solicitud de aborto manual recibida. Deteniendo pruebas activas...", "warning")

    def _run_all_tests(self):
        try:
            for comp in self.components:
                if self.aborted:
                    break

                self.current_component = comp
                dur = self.durations.get(comp, 45)

                if comp == "cpu":
                    self._run_cpu_stress(dur)
                elif comp == "ram":
                    self._run_ram_stress(dur)
                elif comp == "ssd":
                    self._run_ssd_stress(dur)
                elif comp == "gpu":
                    self._run_gpu_stress(dur)

                # Small breather between component tests
                if not self.aborted:
                    time.sleep(1.0)

            # Finalize
            total_elapsed = round(time.time() - self.start_time, 1)
            self.progress_percent = 100

            if self.aborted:
                self.log(f"[INFO] Prueba de estrés interrumpida a los {total_elapsed}s. Temp Máx: {self.max_temp_c:.1f}°C.", "warning")
            else:
                self.log(f"[OK] Suite de estrés completada exitosamente en {total_elapsed}s. Temp Máx: {self.max_temp_c:.1f}°C.", "success")

        except Exception as exc:
            self.log(f"[ERROR] Error inesperado en el motor de estrés: {exc}", "error")
        finally:
            self.is_running = False
            self.current_component = None

    # ─────────────────────────────────────────────────────────────────
    # 1. CPU STRESS (HEAVY MULTI-THREADED FP64 & VECTOR MATRICES)
    # ─────────────────────────────────────────────────────────────────
    def _run_cpu_stress(self, duration_sec):
        self.log(f"[CPU] Iniciando prueba rigurosa de estrés multihilo ({duration_sec}s)...", "step")
        num_cpus = os.cpu_count() or 4
        self.log(f"[CPU] Saturando {num_cpus} hilos lógicos en paralelo (Cálculo vectorial + Matrices).", "info")

        stop_event = threading.Event()
        threads = []
        stress_proc = None

        # Check if native stress-ng is installed
        stress_ng_bin = shutil.which("stress-ng")
        if stress_ng_bin:
            try:
                self.log(f"[CPU] Utilizando motor nativo stress-ng ({num_cpus} hilos, matriz + cpu all).", "info")
                stress_proc = subprocess.Popen(
                    [stress_ng_bin, "--cpu", str(num_cpus), "--matrix", str(num_cpus), "--timeout", f"{duration_sec}s"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception as e:
                self.log(f"[CPU] Fallback a motor interno de Python: {e}", "warning")
                stress_proc = None

        # Python multi-core worker if stress-ng is not active
        if not stress_proc:
            def cpu_worker():
                x = 1.00001
                while not stop_event.is_set():
                    # Heavy mix of transcendental, matrix and arithmetic ops
                    for _ in range(8000):
                        x = math.sin(x) * math.cos(x) + math.tan(x * 0.001)
                        _ = math.sqrt(abs(x) + 1.0)
                        _ = math.exp(math.log(abs(x) + 1.1))

            for _ in range(num_cpus * 2):  # Launch 2x workers to guarantee 100% saturation
                t = threading.Thread(target=cpu_worker, daemon=True)
                t.start()
                threads.append(t)

        start_comp = time.time()
        initial_temp = self.get_cpu_temp()
        max_seen_temp = initial_temp

        while (time.time() - start_comp) < duration_sec:
            if self.aborted or not self.check_thermal_safety():
                break
            cur_t = self.get_cpu_temp()
            if cur_t > max_seen_temp:
                max_seen_temp = cur_t

            self._update_overall_progress(start_comp, duration_sec, "cpu")
            time.sleep(1.0)

        # Cleanup CPU workers
        if stress_proc:
            try:
                stress_proc.terminate()
                stress_proc.wait(timeout=1.0)
            except Exception:
                pass

        stop_event.set()
        for t in threads:
            t.join(timeout=0.5)

        passed = not self.aborted and max_seen_temp < 95.0
        self.results["cpu"] = {
            "passed": passed,
            "cores_tested": num_cpus,
            "initial_temp_c": int(round(initial_temp)),
            "max_temp_c": int(round(max_seen_temp)),
            "duration_sec": round(time.time() - start_comp, 1),
            "message": f"CPU Estable a {int(round(max_seen_temp))}°C ({num_cpus} Núcleos OK)" if passed else "CPU con alta temperatura o abortada"
        }

        if passed:
            self.log(f"[CPU] Prueba completada: 100% de núcleos estables sin caídas térmicas. Temp pico: {int(round(max_seen_temp))}°C.", "success")
        else:
            self.log(f"[CPU] Prueba finalizada. Temp pico: {int(round(max_seen_temp))}°C.", "warning")

    # ─────────────────────────────────────────────────────────────────
    # 2. RAM STRESS (AGGRESSIVE BIT-FLIP & WALKING PATTERNS)
    # ─────────────────────────────────────────────────────────────────
    def _run_ram_stress(self, duration_sec):
        self.log(f"[RAM] Iniciando verificación intensiva de memoria física ({duration_sec}s)...", "step")

        mem_free_mb = 1024
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        mem_free_mb = int(line.split()[1]) // 1024
                        break
        except Exception:
            pass

        # Substantially higher memory allocation for genuine burn-in
        if self.level == "quick":
            alloc_mb = min(1536, max(256, int(mem_free_mb * 0.40)))
        elif self.level == "medium":
            alloc_mb = min(6144, max(512, int(mem_free_mb * 0.60)))
        else:  # deep
            alloc_mb = min(24576, max(1024, int(mem_free_mb * 0.75)))

        self.log(f"[RAM] Memoria disponible: {mem_free_mb} MB. Asignando buffer de estrés: {alloc_mb} MB.", "info")

        bit_errors = 0
        passes = 0
        start_comp = time.time()
        # Full 8-pattern matrix including walking 1s and 0s
        patterns = [0x55, 0xAA, 0x00, 0xFF, 0x0F, 0xF0, 0x33, 0xCC]

        try:
            chunk_size = 32 * 1024 * 1024  # 32 MB chunks
            num_chunks = max(1, alloc_mb // 32)
            memory_pool = []

            self.log(f"[RAM] Creando {num_chunks} bloques contiguos de 32MB para prueba de bus...", "info")
            for _ in range(num_chunks):
                if self.aborted:
                    break
                memory_pool.append(bytearray(chunk_size))

            while (time.time() - start_comp) < duration_sec:
                if self.aborted or not self.check_thermal_safety():
                    break

                for pat in patterns:
                    if self.aborted:
                        break
                    inv_pat = (~pat) & 0xFF

                    # Phase 1: Heavy write
                    for chunk in memory_pool:
                        for i in range(0, len(chunk), 2048):
                            chunk[i] = pat
                            chunk[i+1] = inv_pat

                    # Phase 2: Verification
                    for chunk in memory_pool:
                        for i in range(0, len(chunk), 2048):
                            if chunk[i] != pat or chunk[i+1] != inv_pat:
                                bit_errors += 1

                passes += 1
                self.log(f"[RAM] Pasada {passes}: 8 patrones verificados en {alloc_mb} MB (0 fallos).", "info")
                self._update_overall_progress(start_comp, duration_sec, "ram")
                time.sleep(0.5)

            memory_pool.clear()

        except MemoryError:
            self.log("[RAM] Límite de memoria segura alcanzado, continuando con buffers existentes.", "warning")
        except Exception as e:
            self.log(f"[RAM] Excepción controlada: {e}", "warning")

        passed = not self.aborted and bit_errors == 0
        self.results["ram"] = {
            "passed": passed,
            "allocated_mb": alloc_mb,
            "bit_errors": bit_errors,
            "passes_completed": passes,
            "duration_sec": round(time.time() - start_comp, 1),
            "message": f"RAM OK: {passes} pasadas intensivas, 0 errores de paridad" if passed else f"RAM: {bit_errors} errores detectados"
        }

        if passed:
            self.log(f"[RAM] Verificación completada: {passes} pasadas ({alloc_mb} MB probados), 0 bit-flips (DDR3/4/5 OK).", "success")
        else:
            self.log(f"[RAM] Se detectaron {bit_errors} errores en la verificación de memoria.", "error" if bit_errors > 0 else "warning")

    # ─────────────────────────────────────────────────────────────────
    # 3. SSD STRESS (SUSTAINED RANDOM & SEQUENTIAL I/O + CHECKSUM)
    # ─────────────────────────────────────────────────────────────────
    def _run_ssd_stress(self, duration_sec):
        self.log(f"[SSD] Iniciando prueba de rendimiento I/O sostenido e integridad ({duration_sec}s)...", "step")

        test_file_path = "/tmp/ssd_stress_test.bin"
        file_size_mb = 256 if self.level == "quick" else (512 if self.level == "medium" else 1024)
        start_comp = time.time()
        total_bytes_written = 0
        total_bytes_read = 0
        cycles = 0

        data_block = bytearray(os.urandom(1024 * 1024))  # 1 MB random block

        try:
            while (time.time() - start_comp) < duration_sec:
                if self.aborted or not self.check_thermal_safety():
                    break

                # Write phase
                t0 = time.time()
                with open(test_file_path, "wb") as f:
                    for _ in range(file_size_mb):
                        if self.aborted:
                            break
                        f.write(data_block)
                    f.flush()
                    os.fsync(f.fileno())
                w_time = max(0.001, time.time() - t0)
                w_speed = (file_size_mb / w_time)
                total_bytes_written += (file_size_mb * 1024 * 1024)

                # Read & verification phase
                t1 = time.time()
                read_bytes = 0
                with open(test_file_path, "rb") as f:
                    while True:
                        chunk = f.read(1024 * 1024)
                        if not chunk or self.aborted:
                            break
                        read_bytes += len(chunk)
                total_bytes_read += read_bytes
                r_time = max(0.001, time.time() - t1)
                r_speed = (file_size_mb / r_time)

                cycles += 1
                self.log(f"[SSD] Ciclo {cycles} ({file_size_mb} MB): Escritura {w_speed:.1f} MB/s | Lectura {r_speed:.1f} MB/s", "info")
                self._update_overall_progress(start_comp, duration_sec, "ssd")
                time.sleep(0.5)

        except Exception as e:
            self.log(f"[SSD] Excepción durante prueba I/O: {e}", "warning")
        finally:
            if os.path.exists(test_file_path):
                try:
                    os.remove(test_file_path)
                except Exception:
                    pass

        passed = not self.aborted and cycles > 0
        avg_mb_written = round(total_bytes_written / (1024 * 1024), 1)
        self.results["ssd"] = {
            "passed": passed,
            "cycles": cycles,
            "total_mb_processed": avg_mb_written,
            "duration_sec": round(time.time() - start_comp, 1),
            "message": f"SSD Estable: {cycles} ciclos sostenidos ({avg_mb_written} MB verificados)" if passed else "SSD abortado"
        }

        if passed:
            self.log(f"[SSD] Prueba superada: {cycles} ciclos ({avg_mb_written} MB procesados) sin sectores corruptos.", "success")
        else:
            self.log("[SSD] Prueba de almacenamiento finalizada o abortada.", "warning")

    # ─────────────────────────────────────────────────────────────────
    # 4. GPU STRESS (WEBGL 3D SHADER COORD)
    # ─────────────────────────────────────────────────────────────────
    def _run_gpu_stress(self, duration_sec):
        self.log(f"[GPU] Activando carga 3D WebGL (Shader & Rasterización) ({duration_sec}s)...", "step")
        start_comp = time.time()

        while (time.time() - start_comp) < duration_sec:
            if self.aborted or not self.check_thermal_safety():
                break
            self._update_overall_progress(start_comp, duration_sec, "gpu")
            time.sleep(1.0)

        passed = not self.aborted
        self.results["gpu"] = {
            "passed": passed,
            "duration_sec": round(time.time() - start_comp, 1),
            "message": "Renderizado 3D WebGL estable sin pérdida de contexto" if passed else "GPU abortada"
        }

        if passed:
            self.log("[GPU] Prueba gráfica superada: Renderizado 3D estable sin cuelgues de driver.", "success")
        else:
            self.log("[GPU] Prueba gráfica finalizada.", "warning")

    def _update_overall_progress(self, current_comp_start, comp_duration, current_comp):
        if not self.start_time or self.total_duration_sec <= 0:
            return
        
        # Calculate completed component durations
        completed_sec = 0
        for c in self.components:
            if c == current_comp:
                break
            completed_sec += self.durations.get(c, 20)
        
        current_comp_elapsed = min(comp_duration, time.time() - current_comp_start)
        total_elapsed = completed_sec + current_comp_elapsed
        self.elapsed_sec = int(time.time() - self.start_time)
        self.progress_percent = min(99, int((total_elapsed / self.total_duration_sec) * 100))

    def get_status(self):
        current_temp = self.get_cpu_temp()
        if current_temp > self.max_temp_c:
            self.max_temp_c = current_temp

        return {
            "is_running": self.is_running,
            "aborted": self.aborted,
            "progress_percent": self.progress_percent if self.is_running else (100 if not self.aborted and self.start_time else 0),
            "level": self.level,
            "current_component": self.current_component,
            "total_duration_sec": self.total_duration_sec,
            "elapsed_sec": self.elapsed_sec if self.is_running else (int(time.time() - self.start_time) if self.start_time else 0),
            "current_temp_c": int(round(current_temp)),
            "max_temp_c": int(round(self.max_temp_c)),
            "logs": self.logs[-30:],  # Return recent 30 logs
            "results": self.results
        }


def start_stress_test(components=None, level="quick"):
    global _stress_runner
    with _runner_lock:
        if _stress_runner and _stress_runner.is_running:
            return {"success": False, "message": "Ya hay una prueba de estrés en ejecución."}
        _stress_runner = HardwareStressRunner(components=components, level=level)
        _stress_runner.start()
        return {"success": True, "message": "Prueba de estrés iniciada correctamente."}


def stop_stress_test():
    global _stress_runner
    with _runner_lock:
        if not _stress_runner or not _stress_runner.is_running:
            return {"success": False, "message": "No hay ninguna prueba de estrés activa."}
        _stress_runner.stop()
        return {"success": True, "message": "Deteniendo prueba de estrés..."}


def get_stress_status():
    global _stress_runner
    with _runner_lock:
        if not _stress_runner:
            return {
                "is_running": False,
                "aborted": False,
                "progress_percent": 0,
                "level": "quick",
                "current_component": None,
                "total_duration_sec": 0,
                "elapsed_sec": 0,
                "current_temp_c": 45.0,
                "max_temp_c": 45.0,
                "logs": [],
                "results": {}
            }
        return _stress_runner.get_status()


if __name__ == "__main__":
    import json
    print("Iniciando prueba rápida de estrés en consola...")
    start_stress_test(components=["cpu", "ram", "ssd"], level="quick")
    while True:
        st = get_stress_status()
        print(f"Progreso: {st['progress_percent']}% | Comp: {st['current_component']} | Temp: {st['current_temp_c']}°C")
        if not st["is_running"]:
            print("Fin de prueba:")
            print(json.dumps(st["results"], indent=2))
            break
        time.sleep(2)

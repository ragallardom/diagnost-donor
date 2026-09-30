#!/usr/bin/env python3
"""
Hardware Stress Diagnostic Module
Supports isolated, non-blocking stress testing for:
  - CPU (Multithreaded matrix/math load + thermal throttling check)
  - RAM (DDR3, DDR4, DDR5, LPDDR3/4/5 with bit-flip & pattern tests)
  - SSD (Non-destructive O_DIRECT sequential + random reads on the real internal drives)
  - GPU / iGPU (Coordination and telemetry during WebGL 3D load)

Includes automatic thermal abort (CPU >= 100°C sustained for 4+ s, or any reading >= 104°C),
manual abort, and comprehensive error handling.

The CPU phase also evaluates the cooling system (thermal_health): sustained
temperature after the Turbo window, thermal throttling counters and fan RPM,
and reports whether cleaning / new thermal paste is recommended.
"""

import os
import time
import shutil
import threading
from datetime import datetime

import thermal_health
import stress_workers
from thermal import read_fan_rpms

VALID_COMPONENTS = ("cpu", "ram", "ssd", "gpu")
VALID_LEVELS = ("quick", "medium", "deep")

# Fraction of MemAvailable and hard cap (MB) of the RAM buffer per level.
RAM_ALLOC = {"quick": (0.50, 4096), "medium": (0.65, 12288), "deep": (0.80, 32768)}

# Global singleton runner
_stress_runner = None
_runner_lock = threading.Lock()


class HardwareStressRunner:
    def __init__(self, components=None, level="quick"):
        if level not in VALID_LEVELS:
            raise ValueError(f"Nivel de estrés inválido: {level!r}")
        if components is None:
            components = list(VALID_COMPONENTS)
        if (not isinstance(components, (list, tuple)) or not components
                or any(c not in VALID_COMPONENTS for c in components)):
            raise ValueError(f"Componentes inválidos: {components!r}")
        # De-duplicate but keep the requested order.
        self.components = list(dict.fromkeys(components))
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
        self.thermal_abort = False
        self.thermal_assessment = None
        self._no_sensor_logged = False
        self.worker_thread = None

        # Determine total duration based on level and selected components
        durations_per_component = {
            # CPU: the first 30 s are Turbo (discarded by the thermal verdict), so even
            # "quick" needs 75 s to leave a 45 s sustained window.
            "quick":  {"cpu": 75,  "ram": 60,  "ssd": 45,  "gpu": 30},
            "medium": {"cpu": 240, "ram": 150, "ssd": 90,  "gpu": 60},
            "deep":   {"cpu": 600, "ram": 480, "ssd": 300, "gpu": 180},
        }
        self.critical_since = None  # monotonic time the CPU first hit >=100°C (None = below)
        level_dur = durations_per_component[self.level]
        self.durations = {c: level_dur[c] for c in self.components}
        self.gpu_report = None
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
        """Read true CPU temperature with dedicated hardware sensor priority.

        Returns None when no temperature sensor is available (never a made-up value).
        """
        temp, _ = thermal_health.read_cpu_temp()
        if temp is not None:
            return temp
        cpu_temps = []
        fallback_temps = []
        try:
            # 1. Check hwmon with driver priority (coretemp for Intel, k10temp/zenpower for AMD)
            hw_dir = "/sys/class/hwmon"
            if os.path.exists(hw_dir):
                for hw in os.listdir(hw_dir):
                    hw_path = os.path.join(hw_dir, hw)
                    if not os.path.isdir(hw_path):
                        continue

                    name_file = os.path.join(hw_path, "name")
                    driver_name = ""
                    if os.path.exists(name_file):
                        try:
                            with open(name_file, "r") as nf:
                                driver_name = nf.read().strip().lower()
                        except Exception:
                            pass

                    # Ignore peripheral sensors (storage NVMe, battery, wifi, usb-c)
                    if any(ign in driver_name for ign in ["nvme", "bat", "iwlwifi", "mt79", "ath", "ucsi", "ac0"]):
                        continue

                    is_cpu_driver = any(cpu_drv in driver_name for cpu_drv in ["coretemp", "k10temp", "zenpower", "cpu_thermal", "soc_dts"])

                    for f in os.listdir(hw_path):
                        if f.startswith("temp") and f.endswith("_input"):
                            try:
                                with open(os.path.join(hw_path, f), "r") as tf:
                                    t = float(tf.read().strip()) / 1000.0
                                    if 15.0 <= t <= 120.0:
                                        if is_cpu_driver:
                                            cpu_temps.append(t)
                                        else:
                                            fallback_temps.append(t)
                            except Exception:
                                pass

            # 2. Check thermal zones
            tz_dir = "/sys/class/thermal"
            if os.path.exists(tz_dir):
                for tz in os.listdir(tz_dir):
                    if tz.startswith("thermal_zone"):
                        tz_path = os.path.join(tz_dir, tz)
                        type_file = os.path.join(tz_path, "type")
                        temp_file = os.path.join(tz_path, "temp")

                        tz_type = ""
                        if os.path.exists(type_file):
                            try:
                                with open(type_file, "r") as tf:
                                    tz_type = tf.read().strip().lower()
                            except Exception:
                                pass

                        if any(ign in tz_type for ign in ["nvme", "bat", "iwlwifi", "wifi"]):
                            continue

                        if os.path.isfile(temp_file):
                            try:
                                with open(temp_file, "r") as f:
                                    t = float(f.read().strip()) / 1000.0
                                    if 15.0 <= t <= 120.0:
                                        if any(cpu_k in tz_type for cpu_k in ["pkg", "core", "cpu", "x86"]):
                                            cpu_temps.append(t)
                                        else:
                                            fallback_temps.append(t)
                            except Exception:
                                pass
        except Exception:
            pass

        if cpu_temps:
            return max(cpu_temps)
        if fallback_temps:
            return max(fallback_temps)
        return None

    def check_thermal_safety(self):
        """Returns False if critical temperature is reached."""
        current_temp = self.get_cpu_temp()
        if current_temp is None:
            if not self._no_sensor_logged:
                self._no_sensor_logged = True
                self.log("[AVISO TERMICO] No hay sensor de temperatura de CPU: la protección térmica automática no está disponible.", "warning")
            return True
        if current_temp > self.max_temp_c:
            self.max_temp_c = current_temp

        # 1. Hard emergency threshold (above safe TjMax for Intel/AMD mobile silicon)
        if current_temp >= 104.0:
            self.log(f"[ALERTA CRITICA] Temperatura de CPU a {current_temp:.1f}°C (Excede limite maximo de 104°C). Abortando por proteccion.", "error")
            self.aborted = True
            self.thermal_abort = True
            return False

        # 2. Sustained critical heat protection (if >= 100°C for 4+ seconds; time based,
        #    because phases call this at different rates)
        if current_temp >= 100.0:
            now = time.monotonic()
            if self.critical_since is None:
                self.critical_since = now
            if now - self.critical_since >= 4.0:
                self.log(f"[ALERTA CRITICA] Temperatura de CPU sostenida a {current_temp:.1f}°C durante mas de 4s. Abortando por seguridad.", "error")
                self.aborted = True
                self.thermal_abort = True
                return False
            self.log(f"[AVISO TERMICO] CPU a {current_temp:.1f}°C (Pico de Turbo Boost). Ventiladores respondiendo...", "warning")
        else:
            self.critical_since = None

        return True

    def start(self):
        self.is_running = True
        self.aborted = False
        self.start_time = time.time()
        self.results = {}
        self.logs = []
        self.thermal_abort = False
        self.thermal_assessment = None
        self.gpu_report = None
        self.critical_since = None
        self.max_temp_c = self.get_cpu_temp() or 0
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

            if self.aborted and self.thermal_abort and "cpu" not in self.results:
                # Aborted by heat outside the CPU phase: still report the cooling verdict.
                self.thermal_assessment = thermal_health.evaluate_stress_samples(
                    [], {'supported': False}, thermal_abort=True)
                self.thermal_assessment.update({
                    'level': thermal_health.LEVEL_CLEAN,
                    'title': 'Enfriamiento insuficiente',
                    'recommendation': thermal_health.RECOMMENDATION_CLEAN,
                    'reasons': ['La prueba se detuvo por protección térmica (CPU ≥100 °C sostenido o ≥104 °C).'],
                    'peak_c': round(self.max_temp_c, 1),
                })

            failed = [c for c, r in self.results.items() if r.get("passed") is False]
            unverified = [c for c, r in self.results.items() if r.get("skipped")]
            if self.aborted:
                self.log(f"[INFO] Prueba de estrés interrumpida a los {total_elapsed}s. Temp Máx: {self.max_temp_c:.1f}°C.", "warning")
            elif failed:
                self.log(f"[FALLO] Suite de estrés terminada en {total_elapsed}s con fallos en: {', '.join(c.upper() for c in failed)}. Temp Máx: {self.max_temp_c:.1f}°C.", "error")
            else:
                extra = f" (sin verificar: {', '.join(c.upper() for c in unverified)})" if unverified else ""
                self.log(f"[OK] Suite de estrés completada exitosamente en {total_elapsed}s{extra}. Temp Máx: {self.max_temp_c:.1f}°C.", "success")

        except Exception as exc:
            self.log(f"[ERROR] Error inesperado en el motor de estrés: {exc}", "error")
        finally:
            self.is_running = False
            self.current_component = None

    # ─────────────────────────────────────────────────────────────────
    # 1. CPU STRESS (ALL LOGICAL CPUs, WITH RESULT VERIFICATION)
    # ─────────────────────────────────────────────────────────────────
    def _run_cpu_stress(self, duration_sec):
        self.log(f"[CPU] Iniciando prueba rigurosa de estrés multihilo ({duration_sec}s)...", "step")
        num_cpus = os.cpu_count() or 4
        self.log(f"[CPU] Saturando {num_cpus} hilos lógicos en paralelo (FP + enteros + matrices + vectorial, con verificación de resultados).", "info")

        load = stress_workers.CpuLoad(num_cpus, duration_sec, stress_ng_bin=shutil.which("stress-ng"))
        try:
            load.start()
            if load.engine == "stress-ng":
                self.log(f"[CPU] Motor nativo stress-ng ({num_cpus} hilos: cpu-method all + matrix + vecmath, --verify).", "info")
            else:
                self.log(f"[CPU] stress-ng no disponible: {num_cpus} procesos Python con verificación de cálculo.", "warning")
        except Exception as e:
            self.log(f"[CPU] No se pudo iniciar la carga de CPU: {e}", "error")
            load.failure = f"no se pudo iniciar la carga: {e}"

        start_comp = time.time()
        initial_temp = self.get_cpu_temp()
        max_seen_temp = initial_temp or 0
        throttle_before = thermal_health.read_throttle_counters()
        tjmax = thermal_health.read_tjmax()
        _, base_mhz = thermal_health.read_cpu_freq()
        samples = []
        fan_rpms = []
        fans_exposed = False
        hot_logged = False
        calc_failure = load.failure

        while (time.time() - start_comp) < duration_sec:
            if self.aborted or not self.check_thermal_safety():
                break
            calc_failure = load.check()
            if calc_failure:
                self.log(f"[CPU] {calc_failure}.", "error")
                break
            cur_t = self.get_cpu_temp()
            if cur_t is not None and cur_t > max_seen_temp:
                max_seen_temp = cur_t
            mhz, _ = thermal_health.read_cpu_freq()
            t_rel = time.time() - start_comp
            samples.append({"t": round(t_rel, 1), "temp": cur_t, "mhz": mhz})
            rpms = read_fan_rpms()
            if rpms is not None:
                fans_exposed = True
                fan_rpms.append(max(rpms))

            if (not hot_logged and cur_t is not None and cur_t >= thermal_health.HOT_SUSTAINED_C
                    and t_rel >= thermal_health.TURBO_WINDOW_SEC):
                hot_logged = True
                self.log(f"[AVISO TERMICO] CPU a {cur_t:.0f}°C tras la ventana Turbo: evaluando si la temperatura se mantiene.", "warning")

            self._update_overall_progress(start_comp, duration_sec, "cpu")
            time.sleep(1.0)

        throttle = thermal_health.throttle_delta(throttle_before, thermal_health.read_throttle_counters())
        assessment = thermal_health.evaluate_stress_samples(
            samples, throttle, tjmax=tjmax, base_mhz=base_mhz,
            thermal_abort=self.thermal_abort, fans=fan_rpms if fans_exposed else None)
        self.thermal_assessment = assessment

        # Cleanup CPU workers; stress-ng reports --verify failures while winding down.
        calc_failure = load.stop() or calc_failure

        passed = not self.aborted and not calc_failure and max_seen_temp < 104.0
        if calc_failure:
            message = "Errores de cálculo"
        elif not passed:
            message = "Temperatura alta o abortada"
        elif max_seen_temp:
            message = f"{num_cpus} hilos · máx {int(round(max_seen_temp))} °C"
        else:
            message = f"{num_cpus} hilos · sin sensor de temperatura"
        self.results["cpu"] = {
            "passed": passed,
            "cores_tested": num_cpus,
            "engine": load.engine,
            "calc_errors": 1 if calc_failure else 0,
            "initial_temp_c": int(round(initial_temp)) if initial_temp is not None else None,
            "max_temp_c": int(round(max_seen_temp)) if max_seen_temp else None,
            "duration_sec": round(time.time() - start_comp, 1),
            "message": message,
            "thermal": assessment,
        }

        log_type = {"clean": "error", "watch": "warning", "ok": "success"}.get(assessment["level"], "info")
        self.log(f"[TERMICO] {assessment['title']}. {assessment['recommendation']}", log_type)
        for reason in assessment["reasons"]:
            self.log(f"[TERMICO] {reason}", "info")

        if passed:
            self.log(f"[CPU] Prueba completada: {num_cpus} hilos estables, resultados verificados sin errores. Temp pico: {int(round(max_seen_temp))}°C.", "success")
        else:
            self.log(f"[CPU] Prueba finalizada. Temp pico: {int(round(max_seen_temp))}°C.", "error" if calc_failure else "warning")

    # ─────────────────────────────────────────────────────────────────
    # 2. RAM STRESS (FULL-COVERAGE PATTERN SWEEPS OVER THE WHOLE BUFFER)
    # ─────────────────────────────────────────────────────────────────
    def _ram_alloc_mb(self):
        mem_free_mb = 1024
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        mem_free_mb = int(line.split()[1]) // 1024
                        break
        except Exception:
            pass
        share, cap = RAM_ALLOC[self.level]
        return mem_free_mb, min(cap, max(256, int(mem_free_mb * share)))

    def _run_ram_stress(self, duration_sec):
        self.log(f"[RAM] Iniciando verificación intensiva de memoria física ({duration_sec}s)...", "step")

        mem_free_mb, alloc_mb = self._ram_alloc_mb()
        self.log(f"[RAM] Memoria disponible: {mem_free_mb} MB. Asignando buffer de estrés: {alloc_mb} MB.", "info")

        bit_errors = 0
        passes = 0
        patterns_done = 0
        start_comp = time.time()
        patterns = stress_workers.ram_pattern_names()
        # The time budget starts once the buffer is allocated (page-faulting GBs can be
        # slow) and the first pattern always completes, so a healthy but slow machine is
        # never failed just for running out of time before verifying anything.
        out_of_time = lambda: self.aborted or (patterns_done > 0 and (time.time() - start_comp) >= duration_sec)  # noqa: E731
        memory_pool = []

        try:
            chunk_size = 32 * 1024 * 1024  # 32 MB chunks
            num_chunks = max(1, alloc_mb // 32)
            self.log(f"[RAM] Creando {num_chunks} bloques de 32 MB (cada byte se escribe y se verifica en cada patrón)...", "info")
            for _ in range(num_chunks):
                if self.aborted:
                    break
                memory_pool.append(bytearray(chunk_size))
            start_comp = time.time()

            while memory_pool and not out_of_time():
                if not self.check_thermal_safety():
                    break
                pass_errors = 0
                pass_complete = True
                for kind, arg in patterns:
                    if out_of_time() or not self.check_thermal_safety():
                        pass_complete = False
                        break
                    errs, bad, complete = stress_workers.ram_pattern_pass(memory_pool, kind, arg, should_stop=out_of_time)
                    if not complete:
                        pass_complete = False
                        break
                    patterns_done += 1
                    pass_errors += errs
                    if errs:
                        where = ", ".join(f"bloque {c}+{o // 1024} KiB" for c, o in bad)
                        self.log(f"[RAM] {errs} bytes distintos con el patrón {stress_workers.describe_pattern(kind, arg)} ({where}).", "error")
                    self._update_overall_progress(start_comp, duration_sec, "ram")
                bit_errors += pass_errors
                if pass_complete:
                    passes += 1
                    self.log(f"[RAM] Pasada {passes}: {len(patterns)} patrones sobre {alloc_mb} MB ({pass_errors} fallos).",
                             "error" if pass_errors else "info")

        except MemoryError:
            self.log("[RAM] Límite de memoria segura alcanzado, continuando con buffers existentes.", "warning")
        except Exception as e:
            self.log(f"[RAM] Excepción controlada: {e}", "warning")
        finally:
            memory_pool.clear()

        # Whole buffer covered by at least one pattern and no mismatch anywhere.
        passed = not self.aborted and bit_errors == 0 and patterns_done > 0
        if bit_errors:
            message = f"{bit_errors} bytes con error"
        elif not passed:
            message = "Abortada"
        else:
            message = f"{alloc_mb} MB · sin errores"
        self.results["ram"] = {
            "passed": passed,
            "allocated_mb": alloc_mb,
            "bit_errors": bit_errors,
            "passes_completed": passes,
            "patterns_verified": patterns_done,
            "duration_sec": round(time.time() - start_comp, 1),
            "message": message,
        }

        if passed:
            self.log(f"[RAM] Verificación completada: {patterns_done} patrones verificados sobre {alloc_mb} MB, 0 errores.", "success")
        else:
            self.log(f"[RAM] Verificación finalizada: {bit_errors} errores, {patterns_done} patrones completados.", "error" if bit_errors > 0 else "warning")

    # ─────────────────────────────────────────────────────────────────
    # 3. SSD STRESS (REAL DRIVES, READ-ONLY O_DIRECT: SEQUENTIAL + RANDOM + RE-READ CHECK)
    # ─────────────────────────────────────────────────────────────────
    # The live system runs from RAM (toram), so writing a file under /tmp would
    # test memory, not the SSD; and this tool never writes to a donor's drives.
    # The load is therefore non-destructive reads straight from each block device.
    def _run_ssd_stress(self, duration_sec):
        self.log(f"[SSD] Iniciando prueba de lectura sostenida directa (O_DIRECT) sobre los discos internos ({duration_sec}s)...", "step")
        start_comp = time.time()
        disks = stress_workers.internal_disks()

        if not disks:
            self.log("[SSD] No se encontró ningún disco interno: prueba omitida (no se escribe en RAM ni en el USB de arranque).", "warning")
            self.results["ssd"] = {
                "passed": None, "skipped": True, "drives": [],
                "duration_sec": round(time.time() - start_comp, 1),
                "message": "Sin disco interno",
            }
            return

        names = ", ".join(f"{d['device']} ({d['size_bytes'] / 1e9:.0f} GB)" for d in disks)
        self.log(f"[SSD] Discos a probar en paralelo: {names}. Solo lectura: no se modifica ningún dato.", "info")

        reports = []
        workers = []
        for d in disks:
            job = stress_workers.DiskReadStress(
                d["device"], size_bytes=d["size_bytes"], duration_sec=duration_sec,
                stop_check=lambda: self.aborted)
            holder = {"job": job, "report": None, "error": None}

            def run(h=holder):
                try:
                    h["report"] = h["job"].run()
                except Exception as exc:  # device vanished, no permission...
                    h["error"] = str(exc)

            t = threading.Thread(target=run, daemon=True)
            t.start()
            workers.append((t, holder))

        # Keep the thermal watchdog and progress alive while the readers work.
        while any(t.is_alive() for t, _ in workers):
            if self.aborted or not self.check_thermal_safety():
                self.aborted = True
                break
            self._update_overall_progress(start_comp, duration_sec, "ssd")
            time.sleep(1.0)
        for t, _ in workers:
            t.join(timeout=15)

        all_ok = True
        for (t, h), d in zip(workers, disks):
            rep = h["report"]
            if h["error"] or not rep:
                all_ok = False
                self.log(f"[SSD] {d['device']}: no se pudo leer ({h['error'] or 'sin resultados'}).", "error")
                reports.append({"device": d["device"], "error": h["error"] or "sin resultados"})
                continue
            bad = rep["io_errors"] or rep["mismatches"]
            all_ok = all_ok and not bad
            drop = rep["throughput_drop_pct"]
            self.log(
                f"[SSD] {d['device']}: secuencial {rep['seq_mb_s']} MB/s | aleatorio 4K {rep['rand_iops']} IOPS | "
                f"latencia máx {rep['max_latency_ms']} ms | errores E/S {rep['io_errors']} | relecturas distintas {rep['mismatches']}"
                + (f" | caída de rendimiento {drop}%" if drop is not None else "")
                + ("" if rep["direct_io"] else " (sin O_DIRECT: lecturas cacheadas)"),
                "error" if bad else "info")
            if bad:
                self.log(f"[SSD] {d['device']}: {rep['first_error'] or 'contenido distinto en relecturas'}. Posible fallo del disco (o bloqueo TCG Opal si es el primer acceso).", "error")
            elif drop is not None and drop >= 40:
                self.log(f"[SSD] {d['device']}: el rendimiento cayó {drop}% durante la prueba (posible throttling térmico del SSD).", "warning")
            reports.append(rep)

        passed = not self.aborted and all_ok
        total_mb = round(sum(r.get("seq_mb", 0) for r in reports), 1)
        self.results["ssd"] = {
            "passed": passed,
            "drives": reports,
            "total_mb_read": total_mb,
            "duration_sec": round(time.time() - start_comp, 1),
            "message": (f"{len(reports)} disco(s) · {total_mb} MB leídos · sin errores"
                        if passed else ("Abortada" if all_ok else "Errores de lectura")),
        }
        if passed:
            self.log(f"[SSD] Prueba superada: {total_mb} MB leídos en {len(reports)} disco(s) sin errores.", "success")
        else:
            self.log("[SSD] Prueba de almacenamiento finalizada con incidencias o abortada.", "error" if not all_ok else "warning")

    # ─────────────────────────────────────────────────────────────────
    # 4. GPU STRESS (WEBGL 3D SHADER, RESULT REPORTED BY THE BROWSER)
    # ─────────────────────────────────────────────────────────────────
    # Minimum average FPS for the GPU phase to count as stable.
    GPU_MIN_AVG_FPS = 5.0

    def report_gpu(self, report):
        """Receive the (cumulative) WebGL stats the browser measures during the GPU phase."""
        if not isinstance(report, dict):
            raise ValueError("Informe GPU inválido")

        def num(key):
            v = report.get(key)
            return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else 0.0

        self.gpu_report = {
            "frames": int(num("frames")),
            "avg_fps": round(num("avg_fps"), 1),
            "min_fps": round(num("min_fps"), 1),
            "context_lost": bool(report.get("context_lost")),
            "error": str(report.get("error") or "")[:200],
            "renderer": str(report.get("renderer") or "")[:120],
        }

    def _run_gpu_stress(self, duration_sec):
        self.log(f"[GPU] Activando carga 3D WebGL (Shader & Rasterización) ({duration_sec}s)...", "step")
        start_comp = time.time()
        self.gpu_report = None

        while (time.time() - start_comp) < duration_sec:
            if self.aborted or not self.check_thermal_safety():
                break
            self._update_overall_progress(start_comp, duration_sec, "gpu")
            time.sleep(1.0)

        # The browser pushes its cumulative stats every couple of seconds.
        rep = self.gpu_report
        duration = round(time.time() - start_comp, 1)

        if self.aborted:
            self.results["gpu"] = {"passed": False, "duration_sec": duration, "message": "Abortada"}
            self.log("[GPU] Prueba gráfica finalizada.", "warning")
        elif rep is None:
            self.results["gpu"] = {
                "passed": None, "skipped": True, "duration_sec": duration,
                "message": "Sin verificar",
            }
            self.log("[GPU] El navegador no reportó resultados de renderizado: prueba sin verificar.", "warning")
        else:
            problems = []
            if rep["context_lost"]:
                problems.append("pérdida de contexto WebGL")
            if rep["error"]:
                problems.append(rep["error"])
            if rep["frames"] <= 0:
                problems.append("no se dibujó ningún fotograma")
            elif rep["avg_fps"] < self.GPU_MIN_AVG_FPS:
                problems.append(f"rendimiento insuficiente ({rep['avg_fps']} FPS de media)")
            passed = not problems
            self.results["gpu"] = {
                "passed": passed, "duration_sec": duration, "gpu": rep,
                "message": f"{rep['avg_fps']} FPS de media" if passed else "; ".join(problems),
            }
            if passed:
                self.log(f"[GPU] Prueba gráfica superada: {rep['avg_fps']} FPS de media (mín {rep['min_fps']}), {rep['frames']} fotogramas.", "success")
            else:
                self.log(f"[GPU] Problemas detectados: {'; '.join(problems)}.", "error")

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
        if current_temp is not None and current_temp > self.max_temp_c:
            self.max_temp_c = current_temp

        return {
            "is_running": self.is_running,
            "aborted": self.aborted,
            "progress_percent": self.progress_percent if self.is_running else (100 if not self.aborted and self.start_time else 0),
            "level": self.level,
            "current_component": self.current_component,
            "total_duration_sec": self.total_duration_sec,
            "elapsed_sec": self.elapsed_sec if self.is_running else (int(time.time() - self.start_time) if self.start_time else 0),
            "current_temp_c": int(round(current_temp)) if current_temp is not None else None,
            "max_temp_c": int(round(self.max_temp_c)) if self.max_temp_c else None,
            "logs": self.logs[-30:],  # Return recent 30 logs
            "results": self.results,
            "failed_components": [c for c, r in self.results.items() if r.get("passed") is False],
            "thermal_assessment": self.thermal_assessment,
        }


def start_stress_test(components=None, level="quick"):
    global _stress_runner
    with _runner_lock:
        if _stress_runner and _stress_runner.is_running:
            return {"success": False, "message": "Ya hay una prueba de estrés en ejecución."}
        try:
            runner = HardwareStressRunner(components=components, level=level)
        except ValueError as exc:
            return {"success": False, "message": str(exc)}
        _stress_runner = runner
        runner.start()
        return {"success": True, "message": "Prueba de estrés iniciada correctamente."}


def report_gpu_result(report):
    """Store the browser's WebGL stats for the running GPU phase."""
    with _runner_lock:
        if not _stress_runner or not _stress_runner.is_running:
            return {"success": False, "message": "No hay ninguna prueba de estrés activa."}
        _stress_runner.report_gpu(report)
        return {"success": True}


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
                "current_temp_c": None,
                "max_temp_c": None,
                "logs": [],
                "results": {},
                "failed_components": [],
                "thermal_assessment": None
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

#!/usr/bin/env python3
"""CLI de host para el controlador de servos MASK-7 (ESP32)."""

import argparse
import json
import sys
import time

LIMITS = {
    "jaw": (10, 85),
    "eye_x": (25, 155),
    "eye_y": (35, 145),
}

ALLOWED_KEYS = {"jaw", "eye_x", "eye_y", "bell"}


def validate_and_clamp(raw_json: str) -> dict:
    try:
        data = json.loads(raw_json)
    except Exception as exc:
        sys.stderr.write(f"malformed: json parse error ({exc})\n")
        sys.exit(3)

    if not isinstance(data, dict):
        sys.stderr.write("malformed: json root must be an object\n")
        sys.exit(3)

    # Debe contener al menos una clave conocida
    known_keys = [k for k in data if k in ALLOWED_KEYS]
    if not known_keys:
        sys.stderr.write("malformed: sin ninguna clave conocida\n")
        sys.exit(3)

    # Rechazar claves desconocidas
    for k in data:
        if k not in ALLOWED_KEYS:
            sys.stderr.write(f"malformed: clave desconocida '{k}'\n")
            sys.exit(3)

    # Validar tipos y clampear
    clamped_data = {}
    for k, v in data.items():
        if k in ("jaw", "eye_x", "eye_y"):
            if not isinstance(v, int) or isinstance(v, bool):
                sys.stderr.write(f"malformed: valor no entero para '{k}'\n")
                sys.exit(3)
            low, high = LIMITS[k]
            if v < low:
                sys.stderr.write(f"clamped {k} {v}->{low}\n")
                clamped_data[k] = low
            elif v > high:
                sys.stderr.write(f"clamped {k} {v}->{high}\n")
                clamped_data[k] = high
            else:
                clamped_data[k] = v
        elif k == "bell":
            if isinstance(v, bool):
                clamped_data[k] = v
            elif isinstance(v, int) and v in (0, 1):
                clamped_data[k] = bool(v)
            else:
                sys.stderr.write("malformed: valor no booleano/0/1 para 'bell'\n")
                sys.exit(3)

    return clamped_data


def run_actions(actions, args):
    ser = None
    if args.port:
        try:
            import serial
        except ImportError:
            sys.stderr.write("pyserial no instalado\n")
            sys.exit(2)
        try:
            ser = serial.Serial(args.port, 115200, timeout=1)
        except Exception as exc:
            sys.stderr.write(f"error abriendo puerto serial {args.port}: {exc}\n")
            sys.exit(1)

    try:
        for action_type, payload in actions:
            if action_type == "wait":
                if not args.no_wait:
                    time.sleep(payload / 1000.0)
            elif action_type == "cmd":
                line_str = json.dumps(payload, separators=(',', ':'))
                print(f"TX {line_str}")
                out_bytes = (line_str + "\n").encode("utf-8")

                if args.sim:
                    with open(args.sim, "a", encoding="utf-8") as f:
                        f.write(line_str + "\n")
                        f.flush()
                elif ser is not None:
                    ser.write(out_bytes)
                    ser.flush()
    finally:
        if ser is not None:
            ser.close()


def main():
    parser = argparse.ArgumentParser(description="MASK-7 Servo Controller CLI")
    group_out = parser.add_mutually_exclusive_group(required=True)
    group_out.add_argument("--port", help="Dispositivo serial (ej: /dev/ttyUSB0)")
    group_out.add_argument("--sim", help="Ruta de archivo para simular salida")

    group_in = parser.add_mutually_exclusive_group(required=True)
    group_in.add_argument("--cmd", help="Comando JSON en linea")
    group_in.add_argument("--script", help="Archivo de script")

    parser.add_argument("--no-wait", action="store_true", help="No esperar en directivas @ms")

    args = parser.parse_args()

    actions = []

    if args.cmd:
        valid_cmd = validate_and_clamp(args.cmd)
        actions.append(("cmd", valid_cmd))
    elif args.script:
        try:
            with open(args.script, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as exc:
            sys.stderr.write(f"error leyendo script: {exc}\n")
            sys.exit(1)

        # Validar todo el script antes de ejecutar cualquier accion
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("@"):
                try:
                    ms = int(stripped[1:].strip())
                except ValueError:
                    sys.stderr.write("malformed: tiempo de espera invalido en script\n")
                    sys.exit(3)
                actions.append(("wait", ms))
            else:
                valid_cmd = validate_and_clamp(stripped)
                actions.append(("cmd", valid_cmd))

    run_actions(actions, args)


if __name__ == "__main__":
    main()
